"""OrcaSlicer straight to PocketPrint3D (0.46.0): the printer's own API dialects under /orca/<printer>, lanes for Orca's
filament sync (also while the printer is off) and "Upload and Print" on a switched-off printer: plug on, wait, start."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from printshare import power as plug
from printshare import wake as wake_mod

from .fakes import FakeHomeAssistant, FakeMoonraker
from .test_api import TOKEN, BackgroundFake, api  # noqa: F401 - module fixture

GCODE = Path(__file__).parent / "data" / "orca_cone.gcode"
HA = "http://127.0.0.1:8123"
KEY = {"X-Api-Key": TOKEN}


def run(coro):
    return asyncio.run(coro)


def kind(state):
    return {"standby": "idle", "printing": "active", None: "unknown"}.get(state, "idle")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s


def test_wake_switches_on_and_waits_until_the_printer_answers():
    answers = iter([None, None, None, {"state": "standby"}])
    calls, said = [], []

    async def status():
        a = next(answers)
        if a is None:
            raise OSError("connection refused")
        return a

    async def on():
        calls.append("on")

    clock = Clock()
    assert run(wake_mod.wake(status, kind, on, said.append, timeout=60, poll=5, settle=20, clock=clock,
                             sleep=clock.sleep)) is True
    assert calls == ["on"] and clock.t == 3 * 5 + 20, "two misses, ready on the third poll, then the settle time"
    assert "switching it on" in said[0]


def test_wake_does_nothing_when_the_printer_is_on():
    async def status():
        return {"state": "printing"}           # busy: on; the normal start checks refuse it later

    async def on():
        raise AssertionError("must not switch")

    assert run(wake_mod.wake(status, kind, on, print)) is False


def test_wake_gives_up_after_the_timeout_and_reports_plug_errors():
    async def off():
        raise OSError("refused")

    async def on():
        pass

    clock = Clock()
    with pytest.raises(wake_mod.WakeError, match="did not answer within 10 minutes"):
        run(wake_mod.wake(off, kind, on, print, timeout=600, poll=5, clock=clock, sleep=clock.sleep))
    assert clock.t >= 600

    async def broken():
        raise RuntimeError("Home Assistant not reachable")

    with pytest.raises(wake_mod.WakeError, match="could not be switched on: Home Assistant"):
        run(wake_mod.wake(off, kind, broken, print))


def test_lane_data_in_afcs_layout(api):  # noqa: F811
    lanes = [{"id": "CANVAS_1", "tool": 3, "material": "PLA", "color": "#FF0000", "loaded": True, "spool_id": 7},
             {"id": "CANVAS_2", "tool": 1, "material": None, "color": None, "loaded": False},
             {"id": "ext", "tool": None, "material": "PETG", "loaded": True}]
    assert api.lane_data(lanes) == {
        "lane1": {"color": "#FF0000", "material": "PLA", "bed_temp": None, "nozzle_temp": None, "scan_time": "",
                  "td": "", "lane": "3", "spool_id": 7},
        "lane2": {"color": "", "material": "", "bed_temp": None, "nozzle_temp": None, "scan_time": "", "td": "",
                  "lane": "1", "spool_id": None}}


def test_power_config_keeps_auto_on(tmp_path):
    plug.save(tmp_path, "p", plug.PowerConfig(url=HA, token="t", entity="switch.x", auto_on=True))
    cfg = plug.load(tmp_path, "p")
    assert cfg.auto_on is True and cfg.public()["auto_on"] is True and cfg.token == "t"
    plug.save(tmp_path, "p", plug.PowerConfig(url=HA, token="t", entity="switch.x"))
    assert plug.load(tmp_path, "p").auto_on is False


def _wait(c, job_id, states, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{job_id}", headers={"Authorization": f"Bearer {TOKEN}"}).json()
        if j["state"] in states:
            return j
        time.sleep(0.05)
    raise AssertionError(f"job stuck: {j}")


def _upload(c, start, dialect="moonraker", name="cone.gcode"):
    files = {"file": (name, GCODE.read_bytes(), "application/octet-stream")}
    if dialect == "moonraker":
        return c.post("/orca/dom/server/files/upload", headers=KEY, data={"root": "gcodes", "print": str(start).lower()},
                      files=files)
    return c.post("/orca/dom/api/files/local", headers=KEY, data={"print": str(start).lower()}, files=files)


def _orca_job(c):
    jobs = [j for j in c.get("/api/jobs", headers={"Authorization": f"Bearer {TOKEN}"}).json()]
    return jobs[0]["id"]


def test_orca_talks_to_the_server_like_to_moonraker(api, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api.settings, "config_dir", str(tmp_path))
    with TestClient(api.app) as c:
        assert c.get("/orca/dom/server/info").status_code == 401
        assert c.get("/orca/dom/server/info", headers={"X-Api-Key": "wrong"}).status_code == 401
        assert c.get("/orca/nope/server/info", headers=KEY).status_code == 404
        info = c.get("/orca/dom/server/info", headers=KEY).json()["result"]
        assert info["klippy_state"] == "ready" and info["machine_name"] == "Dominique"
        assert c.get("/orca/dom/api/version", headers=KEY).json()["text"].startswith("OctoPrint")
        # the printer is off: no lanes known yet, a status that says standby
        assert c.get("/orca/dom/server/database/item?namespace=lane_data", headers=KEY).status_code == 404
        q = c.get("/orca/dom/printer/objects/query?print_stats&mmu", headers=KEY).json()["result"]["status"]
        assert q == {"print_stats": {"state": "standby", "filename": ""}}
        with BackgroundFake(FakeMoonraker(afc=True)) as moon:
            moon.state = "standby"
            lanes = c.get("/orca/dom/server/database/item?namespace=lane_data", headers=KEY).json()["result"]
            assert lanes["namespace"] == "lane_data" and lanes["value"]["lane1"]["lane"] in "0123"
            # the real printer answers the status query
            assert c.get("/orca/dom/printer/objects/query?print_stats", headers=KEY).json()["result"]["status"][
                "print_stats"]["filename"] == "cube.gcode"
        # off again: Orca still gets the last lanes
        again = c.get("/orca/dom/server/database/item?namespace=lane_data", headers=KEY).json()["result"]
        assert again["value"] == lanes["value"]
        one = c.get("/orca/dom/server/database/item?namespace=lane_data&key=lane1", headers=KEY).json()["result"]
        assert one["value"] == lanes["value"]["lane1"]
        assert c.get("/orca/dom/server/database/item?namespace=other", headers=KEY).status_code == 404
        # only the start of an uploaded file, nothing else
        r = c.post("/orca/dom/printer/gcode/script", headers=KEY, json={"script": "CANCEL_PRINT"})
        assert r.status_code == 400
        r = c.post("/orca/dom/printer/gcode/script", headers=KEY, json={"script": "SDCARD_PRINT_FILE FILENAME=x.gcode"})
        assert r.status_code == 400 and "not found" in r.json()["detail"]


def test_upload_and_print_switches_the_printer_on(api, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(api.settings, "config_dir", str(tmp_path))
    monkeypatch.setattr(wake_mod, "POLL_S", 0.1)
    monkeypatch.setattr(wake_mod, "SETTLE_S", 0.0)
    monkeypatch.setattr(wake_mod, "STATUS_TIMEOUT_S", 3.0)
    api.JOBS.clear()
    with TestClient(api.app) as c, BackgroundFake(FakeHomeAssistant()) as ha:
        H = {"Authorization": f"Bearer {TOKEN}"}
        body = {"url": HA, "token": "ha-token", "entity": "switch.drucker", "auto_on": True}
        assert c.put("/api/printers/dom/power/config", headers=H, json=body).json()["auto_on"] is True
        # Orca's Moonraker agent: upload without starting, then SDCARD_PRINT_FILE
        r = _upload(c, start=False)
        assert r.status_code == 201 and r.json()["result"]["print_started"] is False
        job = _orca_job(c)
        assert c.get(f"/api/jobs/{job}", headers=H).json()["state"] == "sliced"
        r = c.post("/orca/dom/printer/gcode/script", headers=KEY, json={"script": "SDCARD_PRINT_FILE FILENAME=cone.gcode"})
        assert r.status_code == 200
        end = time.time() + 10
        while ha.states["switch.drucker"] != "on" and time.time() < end:
            time.sleep(0.05)
        assert ha.calls == [("turn_on", "switch.drucker")]
        assert c.get(f"/api/jobs/{job}", headers=H).json()["state"] == "sending", "waits for the printer"
        moon = FakeMoonraker()
        moon.state = "standby"
        with BackgroundFake(moon):                      # the printer has booted
            j = _wait(c, job, ("started", "sliced"))
            assert j["state"] == "started", j
            assert moon.uploads[-1]["print"] == "true" and moon.uploads[-1]["name"] == "cone.gcode"
        assert any("switching it on" in line for line in j["log"])


def test_without_auto_on_a_switched_off_printer_is_not_switched_on(api, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(api.settings, "config_dir", str(tmp_path))
    api.JOBS.clear()
    with TestClient(api.app) as c, BackgroundFake(FakeHomeAssistant()) as ha:
        H = {"Authorization": f"Bearer {TOKEN}"}
        c.put("/api/printers/dom/power/config", headers=H, json={"url": HA, "token": "ha-token", "entity": "switch.drucker"})
        r = _upload(c, start=True, dialect="octoprint")
        assert r.status_code == 201 and r.json()["effectivePrint"] is True
        j = _wait(c, _orca_job(c), ("sliced",), timeout=40)
        assert j["error"] and ha.calls == []


def test_a_busy_printer_after_waking_is_not_started(api, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(api.settings, "config_dir", str(tmp_path))
    api.JOBS.clear()
    with TestClient(api.app) as c, BackgroundFake(FakeHomeAssistant()) as ha, BackgroundFake(FakeMoonraker()) as moon:
        H = {"Authorization": f"Bearer {TOKEN}"}
        c.put("/api/printers/dom/power/config", headers=H,
              json={"url": HA, "token": "ha-token", "entity": "switch.drucker", "auto_on": True})
        moon.state = "printing"
        _upload(c, start=True)
        j = _wait(c, _orca_job(c), ("sliced", "started"))
        assert j["state"] == "sliced" and "busy" in j["error"] and ha.calls == []
        assert not moon.uploads
