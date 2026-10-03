"""Send from OrcaSlicer (docs/WEB.md step 3): keys per printer, the OctoPrint-compatible upload, jobs from desktop G-code,
"Upload and Print" through a bridge with the spool booked."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from .test_cloud import cloud, login  # noqa: F401 - fixture

GCODE = Path(__file__).parent / "data" / "orca_cone.gcode"     # a real OrcaSlicer 2.4.2 G-code, middle cut out


def upload(c, key, name="cone.gcode", data=None, start=False):
    return c.post("/octoprint/api/files/local", headers={"X-Api-Key": key} if key else {},
                  data={"print": "true" if start else "false", "path": ""},
                  files={"file": (name, data if data is not None else GCODE.read_bytes(), "application/octet-stream")})


def test_keys_and_version(cloud):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        ben = login(api, c, "ben@example.com")
        c.post("/api/printers", json={"name": "CC", "type": "elegoo_sdcp"}, headers=h)
        assert c.get("/api/printers/cc/orca-upload", headers=h).json()["enabled"] is False
        assert c.post("/api/printers/cc/orca-upload", headers=ben).status_code == 404    # not Ben's printer
        r = c.post("/api/printers/cc/orca-upload", headers=h).json()
        key = r["key"]
        assert key.startswith("pp3do_") and r["url"].endswith("/octoprint")
        state = c.get("/api/printers/cc/orca-upload", headers=h).json()
        assert state["enabled"] and "key" not in state
        assert c.get("/octoprint/api/version").status_code == 403
        assert c.get("/octoprint/api/version", headers={"X-Api-Key": "pp3do_wrong"}).status_code == 403
        v = c.get("/octoprint/api/version", headers={"X-Api-Key": key}).json()
        assert v["text"].startswith("OctoPrint")                  # OrcaSlicer checks this
        new = c.post("/api/printers/cc/orca-upload", headers=h).json()["key"]
        assert c.get("/octoprint/api/version", headers={"X-Api-Key": key}).status_code == 403, "old key replaced"
        assert c.get("/octoprint/api/version", headers={"X-Api-Key": new}).status_code == 200
        assert c.delete("/api/printers/cc", headers=h).status_code == 200
        assert c.get("/octoprint/api/version", headers={"X-Api-Key": new}).status_code == 403, "printer gone, key gone"


def test_upload_becomes_a_job(cloud):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        c.post("/api/printers", json={"name": "CC", "type": "elegoo_sdcp"}, headers=h)
        key = c.post("/api/printers/cc/orca-upload", headers=h).json()["key"]
        r = upload(c, key, start=True)
        assert r.status_code == 201 and r.json()["done"] and r.json()["effectivePrint"] is False
        jobs = c.get("/api/jobs", headers=h).json()
        assert len(jobs) == 1 and jobs[0]["state"] == "sliced" and jobs[0]["print_time"] == "9m 16s"
        j = c.get(f"/api/jobs/{jobs[0]['id']}", headers=h).json()
        assert j["result"]["filament_g"] == 2.96 and j["result"]["layers"] == 123
        assert j["result"]["profiles"]["filament"] == "Elegoo PLA @ECC"
        assert j["result"]["profiles"]["process"] == "0.20mm Standard @Elegoo CC 0.4 nozzle"
        assert any("app" in line for line in j["log"]), "phone-only printer: start it in the app"
        assert c.get(f"/api/jobs/{j['id']}/gcode", headers=h).content == GCODE.read_bytes()
        # not G-code, too large, no key
        assert upload(c, key, name="model.3mf").status_code == 415
        assert upload(c, key, name="x.bgcode").status_code == 415
        assert upload(c, "", name="a.gcode").status_code == 403
        api.settings.limit_upload_mb = 0
        assert upload(c, key).status_code == 413
        assert len(c.get("/api/jobs", headers=h).json()) == 1, "refused uploads leave no job"


def test_upload_and_print_through_a_bridge(cloud, monkeypatch):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        uid = api.ACCOUNTS.user_for_token(h["Authorization"][7:]).id
        api.ACCOUNTS.save_printer(uid, {"id": "voron", "name": "Voron", "type": "moonraker", "bridge": "b1", "remote": "v"})
        spool = c.post("/spoolman/api/v1/spool", json={"filament": {"name": "PLA Basic", "weight": 1000}}, headers=h).json()
        # the spool used last on this printer (a print from the app)
        api.BOOKINGS.create(uid, "voron", "earlier.gcode", [{"spool": spool["id"], "grams": 1, "label": "PLA Basic"}])
        sent = []

        async def fake_call(bridge, user, method, params, timeout=None):
            sent.append((method, params))
            return {"state": "started", "file": "cone.gcode"}
        monkeypatch.setattr(api.HUB, "call", fake_call)
        key = c.post("/api/printers/voron/orca-upload", headers=h).json()["key"]
        r = upload(c, key, start=True)
        assert r.status_code == 201 and r.json()["effectivePrint"] is True
        jid = r.json()["files"]["local"]["refs"]["resource"].rsplit("/", 1)[1]
        for _ in range(100):
            j = c.get(f"/api/jobs/{jid}", headers=h).json()
            if any("Spool" in line for line in j["log"]):
                break
            time.sleep(0.05)
        assert sent[0][0] == "job.send" and sent[0][1]["start"] and sent[0][1]["confirm"] and sent[0][1]["printer"] == "v"
        assert j["state"] == "started" and j["printer_file"] == "cone.gcode"
        waiting = c.get("/api/bookings", headers=h).json()["waiting"]
        assert [(b["file"], b["uses"][0]["spool"], b["uses"][0]["grams"]) for b in waiting] == [("cone.gcode", spool["id"], 2.96)]
        assert asyncio.iscoroutinefunction(api._orca_print)
