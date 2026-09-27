"""API tests for the app flow (slice -> review -> confirm -> send) against a fake Moonraker.

Preset tests need OrcaSlicer's profile folder: ORCA_PROFILES or ORCA_ROOT/resources/profiles.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from printshare.config import JobOptions, SlicingConfig
from printshare.pipeline import JobResult

from .fakes import FakeMoonraker

PROFILES = Path(os.environ.get("ORCA_PROFILES")
                or Path(os.environ.get("ORCA_ROOT", "/opt/orca"), "resources", "profiles"))
needs_profiles = pytest.mark.skipif(not PROFILES.is_dir(), reason="OrcaSlicer profiles not available")
TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


class BackgroundFake:
    """Runs a fake printer on its own event loop, next to the TestClient's loop."""

    def __init__(self, fake):
        self.fake = fake
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self.fake.start(), self.loop).result(10)
        return self.fake

    def __exit__(self, *exc):
        asyncio.run_coroutine_threadsafe(self.fake.stop(), self.loop).result(10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    d = tmp_path_factory.mktemp("ps")
    cfg = d / "config.yaml"
    cfg.write_text(f"""
api_token: {TOKEN}
orca_profiles_dir: {PROFILES}
work_dir: {d / 'work'}
gcode_dir: {d / 'gcode'}
printers:
  - id: dom
    name: Dominique
    type: moonraker
    url: http://127.0.0.1:7125
    slicing:
      machine_preset: cosmos
""")
    os.environ["PRINTSHARE_CONFIG"] = str(cfg)
    import printshare.api as mod
    return importlib.reload(mod)


@pytest.fixture
def client(api):
    with TestClient(api.app) as c:
        yield c


def _wait(client, job_id, *states, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}", headers=H).json()
        if j["state"] in states:
            return j
        time.sleep(0.05)
    raise AssertionError(f"job stuck in {j['state']}: {j}")


def _fake_prepare(api, monkeypatch, tmp_path):
    seen = {}

    async def fake_prepare(settings, link, printer_id, file_choice, options, out_name=None, progress=None):
        seen.update(link=link, options=options)
        progress("Slicing")
        g = tmp_path / "benchy.gcode"
        g.write_text("PRINT_START\nG1 X1\nPRINT_END\n")
        return JobResult(printer_id, "benchy.stl", str(g), "35m 32s", 11.49, 3.82, 240,
                         {"process": "0.20mm Standard"}, options.process_overrides())

    monkeypatch.setattr(api, "prepare_job", fake_prepare)
    return seen


def test_auth_required(client):
    assert client.get("/api/printers").status_code == 401
    assert client.get("/api/printers", headers=H).json()[0]["id"] == "dom"


def test_app_shell_served(client):
    assert "PrintShare" in client.get("/").text
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["share_target"]["action"] == "/"
    assert client.get("/sw.js").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_slice_review_confirm_send(api, client, monkeypatch, tmp_path):
    seen = _fake_prepare(api, monkeypatch, tmp_path)
    r = client.post("/api/jobs", headers=H, json={
        "link": "https://www.printables.com/model/3161-3d-benchy", "printer": "dom",
        "options": {"supports": "tree", "brim": "off", "infill": 20, "walls": 3}})
    job_id = r.json()["job"]
    j = _wait(client, job_id, "sliced", "error")
    assert j["state"] == "sliced", j
    assert j["result"]["layers"] == 240
    assert j["result"]["overrides"] == {"enable_support": "1", "support_type": "tree(auto)",
                                        "brim_type": "no_brim", "sparse_infill_density": "20%",
                                        "wall_loops": "3"}
    assert seen["options"].supports == "tree"
    assert client.get("/api/jobs", headers=H).json()[0]["id"] == job_id

    # NF-05: no start without explicit confirmation
    r = client.post(f"/api/jobs/{job_id}/send", headers=H, json={"start": True})
    assert r.status_code == 400

    with BackgroundFake(FakeMoonraker()) as fake:
        # DR-03: a busy printer refuses the start, the job stays ready
        r = client.post(f"/api/jobs/{job_id}/send", headers=H, json={"start": True, "confirm": True})
        assert r.status_code == 409 and "busy" in r.json()["detail"]
        fake.state = "standby"
        client.post(f"/api/jobs/{job_id}/send", headers=H, json={"start": True, "confirm": True})
        j = _wait(client, job_id, "started", "sliced")
    assert j["state"] == "started", j
    assert fake.uploads[0]["name"] == "benchy.gcode" and fake.uploads[0]["print"] == "true"
    # a started job can't be sent twice
    assert client.post(f"/api/jobs/{job_id}/send", headers=H,
                       json={"start": True, "confirm": True}).status_code == 409


def test_upload_only_then_send_failure_keeps_job(api, client, monkeypatch, tmp_path):
    _fake_prepare(api, monkeypatch, tmp_path)
    job_id = client.post("/api/jobs", headers=H, json={
        "link": "https://www.printables.com/model/1", "printer": "dom"}).json()["job"]
    _wait(client, job_id, "sliced")
    # printer offline: the job stays sliced with an error, so the user can retry
    client.post(f"/api/jobs/{job_id}/send", headers=H, json={"start": False})
    j = _wait(client, job_id, "sliced", "uploaded", timeout=20)
    assert j["state"] == "sliced" and "Sending failed" in j["error"]
    with BackgroundFake(FakeMoonraker()) as fake:
        client.post(f"/api/jobs/{job_id}/send", headers=H, json={"start": False})
        j = _wait(client, job_id, "uploaded")
    assert fake.uploads[0]["print"] == "false"
    assert client.delete(f"/api/jobs/{job_id}", headers=H).status_code == 200
    assert client.get(f"/api/jobs/{job_id}", headers=H).status_code == 404


def test_invalid_options_rejected(client):
    for opts in ({"supports": "everywhere"}, {"infill": 150}, {"bed_type": "Glass"}):
        r = client.post("/api/jobs", headers=H, json={"link": "https://x.y/a.stl", "options": opts})
        assert r.status_code == 400, opts
    assert client.post("/api/jobs", headers=H, json={"link": "file:///etc/passwd"}).status_code == 400


def test_printer_control(client):
    assert client.post("/api/printers/dom/control", headers=H,
                       json={"action": "cancel"}).status_code == 400
    assert client.post("/api/printers/dom/control", headers=H,
                       json={"action": "explode", "confirm": True}).status_code == 400
    with BackgroundFake(FakeMoonraker()) as fake:
        assert client.post("/api/printers/dom/control", headers=H, json={"action": "pause"}).status_code == 200
        assert client.post("/api/printers/dom/control", headers=H,
                           json={"action": "cancel", "confirm": True}).status_code == 200
    assert fake.actions == ["pause", "cancel"]


def test_job_options_apply():
    base = SlicingConfig(process_overrides={"seam_position": "back"})
    s = JobOptions(filament="Elegoo PETG @ECC", bed_type="High Temp Plate", supports="off", infill=0).apply(base)
    assert s.filament == "Elegoo PETG @ECC" and s.process == base.process
    assert s.process_overrides == {"curr_bed_type": "High Temp Plate", "seam_position": "back",
                                   "enable_support": "0", "sparse_infill_density": "0%"}
    assert base.process_overrides["curr_bed_type"] == "Textured PEI Plate"  # base untouched
    assert JobOptions().apply(base).process_overrides == base.process_overrides


@needs_profiles
def test_options_for_printer(client):
    o = client.get("/api/printers/dom/options", headers=H).json()
    assert "Elegoo PLA @ECC" in o["materials"] and "Elegoo PETG @ECC" in o["materials"]
    assert "0.16mm Optimal @Elegoo CC 0.4 nozzle" in o["processes"]
    expected = {"infill": 15, "walls": 2, "supports": "off", "brim": "auto", "bed_type": "Textured PEI Plate"}
    assert {k: o["defaults"][k] for k in expected} == expected
    fine = client.get("/api/printers/dom/options", headers=H,
                      params={"process": "0.12mm Fine @Elegoo CC 0.4 nozzle"}).json()
    assert fine["defaults"]["layer_height"] == "0.12"


@needs_profiles
def test_incompatible_material_rejected(client):
    r = client.post("/api/jobs", headers=H, json={
        "link": "https://x.y/a.stl", "printer": "dom", "options": {"filament": "Bambu PLA Basic @BBL X1C"}})
    assert r.status_code == 400 and "does not fit" in r.json()["detail"]


def test_info_and_printer_kind(api, client):
    assert client.get("/api/info", headers=H).json()["name"] == "PrintShare"
    with BackgroundFake(FakeMoonraker()):
        st = client.get("/api/printers/dom/status", headers=H).json()
    assert st["state"] == "printing" and st["kind"] == "active"
    assert [api.printer_kind(s) for s in ("standby", "paused", "complete", None, "preheating")] == \
        ["idle", "paused", "done", "unknown", "active"]


def test_upload_then_slice(api, client, monkeypatch, tmp_path):
    seen = _fake_prepare(api, monkeypatch, tmp_path)
    assert client.post("/api/uploads", headers=H, params={"name": "evil.sh"}, content=b"x").status_code == 400
    assert client.post("/api/uploads", headers=H, params={"name": "a.stl"}, content=b"").status_code == 400
    up = client.post("/api/uploads", headers=H, params={"name": "../My Part.stl"}, content=b"solid x\n").json()
    assert up["name"] == "My Part.stl" and up["size"] == 8 and up["link"].startswith("upload:")
    assert client.get("/api/files", headers=H, params={"link": up["link"]}).json()[0]["name"] == "My Part.stl"
    job_id = client.post("/api/jobs", headers=H, json={"link": up["link"], "printer": "dom"}).json()["job"]
    _wait(client, job_id, "sliced")
    assert seen["link"].endswith("My Part.stl") and Path(seen["link"]).read_bytes() == b"solid x\n"
    # only ids of real uploads are accepted, never paths
    for bad in ("upload:../../etc", "upload:000000000000", "/etc/passwd"):
        assert client.post("/api/jobs", headers=H, json={"link": bad}).status_code in (400, 404), bad


def test_search_endpoints(api, client, monkeypatch):
    import httpx

    from printshare.search import Search

    from .test_search import router
    monkeypatch.setattr(api, "_SEARCH", Search("", http=httpx.Client(transport=httpx.MockTransport(router))))
    assert client.get("/api/sources").status_code == 401
    assert [s["available"] for s in client.get("/api/sources", headers=H).json()] == [True, False]
    r = client.get("/api/search", headers=H, params={"q": "benchy", "sort": "popular"}).json()
    assert r["results"][0]["id"] == "3161"
    assert client.get("/api/models/printables/3161", headers=H).json()["recommended"]["material"] == "PLA"
    assert client.get("/api/models/printables/404", headers=H).status_code == 404
    assert client.get("/api/search", headers=H, params={"q": "x", "source": "thingiverse"}).status_code == 400
