"""OrcaSlicer straight to PocketPrint3D (0.46.0): the printer's own API dialects under /orca/<printer>, lanes for Orca's
filament sync (also while the printer is off) and "Upload and Print" on a switched-off printer: plug on, wait, start."""
from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
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


# ---------- 0.50.0: the app starts a print on a switched-off printer, slots from the last known lanes ----------
def test_mismatches_compare_slot_content():
    from printshare import lanes as lane_map
    lanes = [{"id": "lane1", "tool": 0, "loaded": True, "material": "PLA", "color": "#FFFFFF"},
             {"id": "lane3", "tool": 2, "loaded": True, "material": "PETG", "color": "#1E88E5"},
             {"id": "lane4", "tool": 3, "loaded": False, "material": None, "color": None}]
    ok = {0: {"material": "pla", "color": "#ffffffff"}, 2: {"material": None, "color": None}}
    assert lane_map.mismatches(lanes, ok) == []
    got = lane_map.mismatches(lanes, {0: {"material": "PETG"}, 2: {"material": "PETG", "color": "#000000"},
                                      3: {}, 5: {}})
    # another colour of the same material is fine
    assert [(p["tool"], p["problem"]) for p in got] == [(0, "material"), (3, "empty"), (5, "missing")]
    assert got[0]["found"] == "PLA" and got[0]["expected"] == "PETG"
    assert "now holds material PLA instead of PETG" in lane_map.describe(got[0])
    # an upload without start doesn't need filament in the slot
    assert lane_map.mismatches(lanes, {3: {}}, start=False) == []


def _sliced_job(c):
    r = _upload(c, start=False)
    assert r.status_code == 201
    return _orca_job(c)


def test_app_switches_on_with_auto_on_and_checks_the_slots(api, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(api.settings, "config_dir", str(tmp_path))
    monkeypatch.setattr(wake_mod, "POLL_S", 0.1)
    monkeypatch.setattr(wake_mod, "SETTLE_S", 0.0)
    monkeypatch.setattr(wake_mod, "STATUS_TIMEOUT_S", 3.0)
    api.JOBS.clear()
    H = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(api.app) as c:
        # off, never seen: no lanes known
        r = c.get("/api/printers/dom/lanes", headers=H).json()
        assert r == {"lanes": [], "live": False, "seen_at": None, "kind": "offline"}
        with BackgroundFake(FakeMoonraker(afc=True)) as moon:
            moon.state = "standby"
            live = c.get("/api/printers/dom/lanes", headers=H).json()
            assert live["live"] is True and len(live["lanes"]) == 4
        # off again: the last lanes, marked as not live
        off = c.get("/api/printers/dom/lanes", headers=H).json()
        assert off["live"] is False and off["lanes"] == live["lanes"] and off["seen_at"]
        printers = c.get("/api/printers", headers=H).json()
        assert printers[0]["power"] is False and printers[0]["auto_on"] is False

        job = _sliced_job(c)
        pla = next(ln for ln in off["lanes"] if ln["material"] == "PLA")
        expect = {str(pla["tool"]): {"material": "PLA", "color": pla["color"]}}
        body = {"start": True, "confirm": True, "wake": True, "lanes": {"1": pla["tool"]}, "expect": expect}
        with BackgroundFake(FakeHomeAssistant()) as ha:
            c.put("/api/printers/dom/power/config", headers=H,
                  json={"url": HA, "token": "ha-token", "entity": "switch.drucker", "auto_on": True})
            assert c.get("/api/printers", headers=H).json()[0]["auto_on"] is True
            assert c.post(f"/api/jobs/{job}/send", headers=H, json=body).status_code == 200
            end = time.time() + 10
            while ha.states["switch.drucker"] != "on" and time.time() < end:
                time.sleep(0.05)
            assert ha.calls == [("turn_on", "switch.drucker")]
            # while it was off someone put PETG into that slot: not started
            from .fakes import AFC_LANES
            lane_key = next(k for k, v in AFC_LANES.items() if v["material"] == "PLA" and
                            ("#" + v["color"].lstrip("#").upper()) == pla["color"])
            moon = FakeMoonraker(afc=True)
            moon.state = "standby"
            monkeypatch.setitem(AFC_LANES, lane_key, {**AFC_LANES[lane_key], "material": "PETG"})
            with BackgroundFake(moon):
                # 0.51.0: the printer is on now - the job waits for the user instead of giving up
                j = _wait(c, job, ("started", "sliced", "needs_decision"))
                assert j["state"] == "needs_decision" and j["decision"]["until"] > time.time(), j
                assert j["slot_problems"][0]["problem"] == "material" and not moon.uploads
                assert c.post(f"/api/jobs/{job}/decision", headers=H, json={"action": "abort"}).status_code == 200
                j = _wait(c, job, ("started", "sliced"))
                assert j["state"] == "sliced" and "PETG instead of PLA" in j["error"], j
                assert "cancelled" in j["error"] and not moon.uploads
            # the right spool again: started
            monkeypatch.setitem(AFC_LANES, lane_key, {**AFC_LANES[lane_key], "material": "PLA"})
            moon = FakeMoonraker(afc=True)
            moon.state = "standby"
            with BackgroundFake(moon):
                assert c.post(f"/api/jobs/{job}/send", headers=H, json=body).status_code == 200
                j = _wait(c, job, ("started", "sliced"))
                assert j["state"] == "started", j
                assert moon.uploads[-1]["print"] == "true" and not j.get("slot_problems")


def test_wrong_material_after_waking_asks_the_user(api, tmp_path, monkeypatch):  # noqa: F811
    """0.51.0: the printer is on, a slot holds another material - a notification asks; start anyway (confirmed) or
    nobody answers (printer off again)."""
    from printshare.push import notify
    from .fakes import AFC_LANES

    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(api.settings, "config_dir", str(tmp_path))
    monkeypatch.setattr(wake_mod, "POLL_S", 0.1)
    monkeypatch.setattr(wake_mod, "SETTLE_S", 0.0)
    monkeypatch.setattr(wake_mod, "STATUS_TIMEOUT_S", 3.0)
    api.JOBS.clear()
    sent = []

    async def relay(handle, secret, msg):
        sent.append(msg)

    monkeypatch.setattr(api, "_NOTIFIER", notify.Notifier(tmp_path / "push.db", relay))
    key = notify.new_key()
    api._notifier().add("local", "pp3dp_" + "a" * 30, "s" * 20, key, "iPhone", "de")
    H = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(api.app) as c:
        with BackgroundFake(FakeMoonraker(afc=True)) as moon:
            moon.state = "standby"
            lanes = c.get("/api/printers/dom/lanes", headers=H).json()["lanes"]
        pla = next(ln for ln in lanes if ln["material"] == "PLA")
        lane_key = next(k for k, v in AFC_LANES.items() if v["material"] == "PLA" and
                        ("#" + v["color"].lstrip("#").upper()) == pla["color"])
        monkeypatch.setitem(AFC_LANES, lane_key, {**AFC_LANES[lane_key], "material": "PETG"})
        body = {"start": True, "confirm": True, "wake": True, "lanes": {"1": pla["tool"]},
                "expect": {str(pla["tool"]): {"material": "PLA", "color": pla["color"]}}}
        with BackgroundFake(FakeHomeAssistant()) as ha:
            c.put("/api/printers/dom/power/config", headers=H,
                  json={"url": HA, "token": "ha-token", "entity": "switch.drucker", "auto_on": True})
            # 1) start anyway
            job = _sliced_job(c)
            assert c.post(f"/api/jobs/{job}/send", headers=H, json=body).status_code == 200
            end = time.time() + 10
            while ha.states["switch.drucker"] != "on" and time.time() < end:
                time.sleep(0.05)
            moon = FakeMoonraker(afc=True)
            moon.state = "standby"
            with BackgroundFake(moon):
                _wait(c, job, ("needs_decision",))
                end = time.time() + 5
                while not any(m.get("category") == "SLOT_CHECK" for m in sent) and time.time() < end:
                    time.sleep(0.05)
                alert = next(m for m in sent if m.get("category") == "SLOT_CHECK")
                raw = base64.b64decode(alert["data"])
                text = ChaCha20Poly1305(base64.b64decode(key)).decrypt(raw[:12], raw[12:], None).decode()
                assert "PETG statt PLA" in text and alert["level"] == "time-sensitive"
                r = c.post(f"/api/jobs/{job}/decision", headers=H, json={"action": "start"})
                assert r.status_code == 400, "starting needs confirm (NF-05)"
                assert c.post(f"/api/jobs/{job}/decision", headers=H,
                              json={"action": "start", "confirm": True}).status_code == 200
                j = _wait(c, job, ("started", "sliced"))
                assert j["state"] == "started" and moon.uploads[-1]["print"] == "true", j
                assert c.post(f"/api/jobs/{job}/decision", headers=H, json={"action": "abort"}).status_code == 409
            # 2) nobody answers: not started, the plug goes off again
            monkeypatch.setattr(api, "DECISION_S", 0.3)
            ha.states["switch.drucker"] = "off"
            job = _sliced_job(c)
            assert c.post(f"/api/jobs/{job}/send", headers=H, json=body).status_code == 200
            end = time.time() + 10
            while ha.states["switch.drucker"] != "on" and time.time() < end:
                time.sleep(0.05)
            moon = FakeMoonraker(afc=True)
            moon.state = "standby"
            with BackgroundFake(moon):
                j = _wait(c, job, ("sliced", "started"))
                assert j["state"] == "sliced" and "nobody answered" in j["error"] and not moon.uploads, j
            assert ha.calls[-1] == ("turn_off", "switch.drucker")
