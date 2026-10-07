"""Started jobs follow their print (0.33.0): finished / cancelled, from every place that sees the printer."""
from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from printshare import jobtrack

from .test_cloud import cloud, fake_slicing, login, wait  # noqa: F401 - fixture

T0 = 1_000_000.0


def started(**kw):
    return {"id": "j", "state": "started", "started_at": T0, "printer_file": "cube.gcode", **kw}


def st(state, file="cube.gcode", progress=None):
    return {"state": state, "file": file, "progress": progress}


def test_rules():
    j = started()
    assert jobtrack.track(j, st("printing", progress=40), "active", T0 + 60) and j["seen_printing"] and j["progress"] == 40
    assert jobtrack.track(j, st("complete"), "done", T0 + 900) and j["state"] == "finished" and j["progress"] == 100
    assert not jobtrack.track(j, st("printing"), "active", T0 + 1000), "a finished job stays finished"
    # the printer still shows the previous run of the same file right after the start
    j = started()
    assert not jobtrack.track(j, st("complete"), "done", T0 + 30) and j["state"] == "started"
    assert not jobtrack.track(j, st("cancelled"), "stopped", T0 + 30) and j["state"] == "started"
    assert jobtrack.track(j, st("complete"), "done", T0 + 11 * 60) and j["state"] == "finished", "finished while nobody looked"
    j = started(seen_printing=True, progress=30)
    assert jobtrack.track(j, st("cancelled", progress=30), "stopped", T0 + 60) and j["state"] == "cancelled"
    # the printer moved on to another file
    j = started(seen_printing=True, progress=99.5)
    assert jobtrack.track(j, st("printing", "other.gcode"), "active", T0 + 60) and j["state"] == "finished"
    j = started(seen_printing=True, progress=60)
    assert jobtrack.track(j, st("standby", "other.gcode"), "idle", T0 + 60) and j["state"] == "cancelled"
    j = started()
    assert not jobtrack.track(j, st("standby", "other.gcode"), "idle", T0 + 60), "never seen: nothing is guessed"
    assert not jobtrack.track(j, None, None, T0 + 60)
    # the name on the printer: bridge sends know it, others use the G-code's file name
    assert jobtrack.printer_file({"result": {"gcode": "/g/cc/j1/Cube.gcode"}}) == "Cube.gcode"


def test_phone_relay_and_observe_and_print_again(cloud, monkeypatch, tmp_path):  # noqa: F811
    api = cloud
    fake_slicing(api, monkeypatch, tmp_path)
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        c.post("/api/printers", json={"name": "CC", "type": "elegoo_sdcp"}, headers=h)
        jid = c.post("/api/jobs", json={"link": "https://www.printables.com/model/1-cube", "printer": "cc"}, headers=h).json()["job"]
        wait(c, h, jid, "sliced")
        # the phone sent it itself on the Wi-Fi
        assert c.post(f"/api/jobs/{jid}/relayed", json={"start": True, "file": "cube.gcode"}, headers=h).json()["state"] == "started"
        assert c.post(f"/api/jobs/{jid}/relayed", json={"start": True, "file": "x.gcode"}, headers=h).status_code == 409
        # and reports what the printer does
        c.post("/api/observe", json={"statuses": {"cc": {"state": "printing", "file": "cube.gcode", "progress": 50}}}, headers=h)
        j = c.get(f"/api/jobs/{jid}", headers=h).json()
        assert j["state"] == "started" and j["seen_printing"] and j["progress"] == 50
        c.post("/api/observe", json={"statuses": {"cc": {"state": "complete", "file": "cube.gcode", "progress": 100}}}, headers=h)
        assert c.get(f"/api/jobs/{jid}", headers=h).json()["state"] == "finished"
        assert [x["state"] for x in c.get("/api/jobs", headers=h).json()] == ["finished"]
        # print it again: allowed, and followed afresh
        assert c.post(f"/api/jobs/{jid}/relayed", json={"start": True, "file": "cube.gcode"}, headers=h).status_code == 200
        j = c.get(f"/api/jobs/{jid}", headers=h).json()
        assert j["state"] == "started" and not j["seen_printing"] and j["progress"] is None
        # other accounts' reports don't touch it
        ben = login(api, c, "ben@example.com")
        c.post("/api/observe", json={"statuses": {"cc": {"state": "complete", "file": "cube.gcode"}}}, headers=ben)
        assert c.get(f"/api/jobs/{jid}", headers=h).json()["state"] == "started"


def test_cloud_follows_bridge_printers(cloud, monkeypatch):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        uid = api.ACCOUNTS.user_for_token(h["Authorization"][7:]).id
        api.ACCOUNTS.save_printer(uid, {"id": "voron", "name": "Voron", "type": "moonraker", "bridge": "b1", "remote": "v"})
        api.JOBS["bj"] = {"id": "bj", "owner": uid, "state": "started", "printer": "voron", "printer_file": "cube.gcode",
                          "started_at": time.time() - 3600, "created": time.time(), "log": [], "result": {"printer": "voron"}}
        statuses = iter([{"state": "printing", "file": "cube.gcode", "progress": 80}, {"state": "complete", "file": "cube.gcode"}])

        async def fake_call(bridge, user, method, params, timeout=None):
            return next(statuses)
        monkeypatch.setattr(api.HUB, "online", lambda b: True)
        monkeypatch.setattr(api.HUB, "call", fake_call)
        asyncio.run(api._check_bridge_bookings())
        assert api.JOBS["bj"]["state"] == "started" and api.JOBS["bj"]["progress"] == 80
        asyncio.run(api._check_bridge_bookings())
        assert api.JOBS["bj"]["state"] == "finished"


def test_external_rules():
    pr = st("printing", "Orca_Cube.gcode", 12.34)
    ext = jobtrack.external([], "cc", pr, "active", T0)
    assert ext["kind"] == "external" and ext["state"] == "started" and ext["printer_file"] == "Orca_Cube.gcode"
    assert ext["seen_printing"] and ext["progress"] == 12.3 and ext["request"]["link"] is None
    assert jobtrack.external([], "cc", st("printing", "sub/dir/x.gcode"), "active", T0)["printer_file"] == "x.gcode"
    # nothing printing, no file
    assert jobtrack.external([], "cc", st("complete", "x.gcode"), "done", T0) is None
    assert jobtrack.external([], "cc", st("printing", None), "active", T0) is None
    assert jobtrack.external([], "cc", None, None, T0) is None
    # a job stands for it already (ours or an earlier external one)
    assert jobtrack.external([started(seen_printing=True)], "cc", st("printing", "Cube.GCODE"), "active", T0) is None
    # our own send is under way, or our start isn't seen yet (the printer may name the file differently)
    assert jobtrack.external([{"state": "sending"}], "cc", pr, "active", T0) is None
    assert jobtrack.external([started()], "cc", pr, "active", T0 + 60) is None
    assert jobtrack.external([started()], "cc", pr, "active", T0 + 21 * 60) is not None
    # finished jobs of the same file don't count: the file was started again elsewhere
    assert jobtrack.external([started(state="finished")], "cc", st("printing"), "active", T0) is not None


def test_external_prints_become_jobs(cloud):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        c.post("/api/printers", json={"name": "CC", "type": "elegoo_sdcp"}, headers=h)
        c.post("/api/observe", json={"statuses": {"cc": {"state": "printing", "file": "orca_cube.gcode", "progress": 5}}},
               headers=h)
        jobs = c.get("/api/jobs", headers=h).json()
        assert [(j["kind"], j["state"], j["file"], j["progress"], j["link"]) for j in jobs] == \
            [("external", "started", "orca_cube.gcode", 5, None)]
        # seen again: the same job, followed until the end
        c.post("/api/observe", json={"statuses": {"cc": {"state": "printing", "file": "orca_cube.gcode", "progress": 60}}},
               headers=h)
        c.post("/api/observe", json={"statuses": {"cc": {"state": "complete", "file": "orca_cube.gcode"}}}, headers=h)
        jobs = c.get("/api/jobs", headers=h).json()
        assert [(j["state"], j["progress"]) for j in jobs] == [("finished", 100.0)]
        j = c.get(f"/api/jobs/{jobs[0]['id']}", headers=h).json()
        assert j["printer"] == "cc" and j["printer_file"] == "orca_cube.gcode" and j["result"] is None
        assert c.get(f"/api/jobs/{j['id']}/gcode", headers=h).status_code in (404, 409)
        assert c.post(f"/api/jobs/{j['id']}/relayed", json={"start": True, "file": "x.gcode"}, headers=h).status_code == 409
        # printed again from the printer: a new job
        c.post("/api/observe", json={"statuses": {"cc": {"state": "printing", "file": "orca_cube.gcode", "progress": 1}}},
               headers=h)
        assert [x["state"] for x in c.get("/api/jobs", headers=h).json()] == ["started", "finished"]


def test_cloud_sees_prints_started_elsewhere_on_bridge_printers(cloud, monkeypatch):  # noqa: F811
    from types import SimpleNamespace
    api = cloud
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        uid = api.ACCOUNTS.user_for_token(h["Authorization"][7:]).id
        api.ACCOUNTS.save_printer(uid, {"id": "voron", "name": "Voron", "type": "moonraker", "bridge": "b1", "remote": "v"})
        calls = []

        async def fake_call(bridge, user, method, params, timeout=None):
            calls.append(params["printer"])
            return {"state": "printing", "file": "from_orca.gcode", "progress": 20}
        monkeypatch.setattr(api.HUB, "conns", {"b1": SimpleNamespace(bridge_id="b1", user_id=uid)})
        monkeypatch.setattr(api.HUB, "online", lambda b: True)
        monkeypatch.setattr(api.HUB, "call", fake_call)
        asyncio.run(api._check_bridge_bookings())
        assert calls == ["v"]
        assert [(j["kind"], j["file"], j["printer"]) for j in c.get("/api/jobs", headers=h).json()] == \
            [("external", "from_orca.gcode", "voron")]
