"""Time-lapse (0.32.0): rendering, the recorder (per layer / every 30 s, end of print, restart), the home server's
endpoints and the upload from a bridge to the cloud job."""
from __future__ import annotations

import asyncio
import io
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from printshare import timelapse as tl

from .test_cloud import cloud, login  # noqa: F401 - fixture


def jpeg(i: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 180), (i * 20 % 255, 80, 160)).save(buf, "JPEG")
    return buf.getvalue()


def test_render(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(1, 13):
        (frames / f"{i:05d}.jpg").write_bytes(jpeg(i))
    out = tl.render(frames, tmp_path / "v.mp4")
    data = out.read_bytes()
    assert data[4:8] == b"ftyp" and len(data) > 1000
    with pytest.raises(RuntimeError):
        empty = tmp_path / "empty"
        empty.mkdir()
        tl.render(empty, tmp_path / "x.mp4")


def make(tmp_path, statuses):
    shots, states = [], []

    async def status(pid):
        return statuses[0]

    async def snap(pid):
        shots.append(pid)
        return jpeg(len(shots))

    async def on_state(rec):
        states.append(rec.state)
    kind = lambda s: {"printing": "active", "complete": "done", "standby": "idle"}.get(s, "unknown")  # noqa: E731
    return tl.TimelapseRecorder(lambda: str(tmp_path / "work"), status, snap, kind, on_state=on_state), shots, states


def test_recorder_per_layer_and_end(tmp_path):
    st = [{"state": "printing", "file": "cube.gcode", "layer": 1}]
    rec_, shots, states = make(tmp_path, st)
    rec = rec_.start("voron", "j1", "cube.gcode", tmp_path / "job")
    assert (tmp_path / "work" / "timelapse" / "active.json").is_file()

    async def run():
        for layer in (1, 1, 2, 3, 3):
            st[0] = {"state": "printing", "file": "cube.gcode", "layer": layer}
            await rec_.check(rec)
        assert rec.frames == 3 and len(shots) == 3
        # a restart in between: the recording is still there
        again, *_ = make(tmp_path, st)
        assert again.active["voron"].frames == 3
        st[0] = {"state": "complete", "file": "cube.gcode", "layer": 3}
        await rec_.check(rec)
    asyncio.run(run())
    assert rec.state == "ready" and (tmp_path / "job" / "timelapse.mp4").is_file()
    assert not Path(rec.frames_dir).exists() and "voron" not in rec_.active
    assert states[-2:] == ["rendering", "ready"]


def test_recorder_by_time_and_waiting(tmp_path):
    st = [{"state": "printing", "file": "part.gcode", "layer": None}]
    rec_, shots, _ = make(tmp_path, st)
    rec = rec_.start("mk4", "j2", "PART.GCODE", tmp_path / "job2")
    t0 = time.time()

    async def run():
        for dt in (0, 10, 31, 45, 62):
            await rec_.check(rec, now=t0 + dt)
        assert rec.frames == 3                                   # at 0, 31 and 62 s
        st[0] = None                                             # printer unreachable: keep waiting
        await rec_.check(rec, now=t0 + 600)
        assert rec.state == "recording"
        st[0] = {"state": "standby", "file": "other.gcode"}    # another file: the print is over
        await rec_.check(rec, now=t0 + 700)
    asyncio.run(run())
    assert rec.state == "ready"


def test_home_server_records_and_serves(tmp_path, monkeypatch):
    import importlib
    import yaml
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"api_token": "t", "work_dir": str(tmp_path / "w"), "gcode_dir": str(tmp_path / "g"),
                                   "printers": [{"id": "cc", "type": "elegoo_sdcp", "host": "127.0.0.1"}]}))
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    h = {"Authorization": "Bearer t"}
    gdir = tmp_path / "g" / "cc" / "j9"
    gdir.mkdir(parents=True)
    (gdir / "cube.gcode").write_text("G1")

    async def fake_send_job(*a, **k):
        return None
    async def idle(self):
        return {"state": "standby"}
    monkeypatch.setattr(api, "send_job", fake_send_job)
    monkeypatch.setattr(type(api.get_adapter(api.settings.printer("cc"))), "status", idle)
    api.JOBS["j9"] = {"id": "j9", "owner": "local", "kind": "prepare", "state": "sliced", "created": time.time(), "log": [],
                      "error": None, "request": {"link": "x"}, "printer": "cc",
                      "result": {"printer": "cc", "source_file": "cube.stl", "gcode": str(gdir / "cube.gcode"),
                                 "print_time": "1m", "filament_g": 1, "filament_m": 0.3}}
    with TestClient(api.app) as c:
        assert c.post("/api/jobs/j9/send", json={"start": True, "confirm": True, "timelapse": True}, headers=h).status_code == 200
        for _ in range(50):
            if api.JOBS["j9"]["state"] == "started":
                break
            time.sleep(0.05)
        assert api.JOBS["j9"]["timelapse"]["state"] == "recording"
        rec = api.TIMELAPSE.get("j9")
        assert rec.file == "cube.gcode" and rec.out == str(gdir / "timelapse.mp4")
        assert c.get("/api/jobs/j9/timelapse", headers=h).status_code == 404
        for i in range(1, 6):
            (Path(rec.frames_dir) / f"{i:05d}.jpg").write_bytes(jpeg(i))
        rec.frames, rec.seen_active = 5, True
        asyncio.run(api.TIMELAPSE.finish(rec))
        assert api.JOBS["j9"]["timelapse"]["state"] == "ready"
        r = c.get("/api/jobs/j9/timelapse", headers=h)
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and r.content[4:8] == b"ftyp"
        assert "inline" in r.headers["content-disposition"] and "cube-timelapse.mp4" in r.headers["content-disposition"]


def test_bridge_uploads_to_the_cloud_job(cloud, tmp_path):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        h = login(api, c, "anna@example.com")
        uid = api.ACCOUNTS.user_for_token(h["Authorization"][7:]).id
        bid = str(uuid.uuid4())
        start = api.BRIDGES.start_pairing(bid)
        api.BRIDGES.confirm_pairing(uid, start["code"])
        token = api.BRIDGES.poll_pairing(bid, start["poll"])["token"]
        jdir = tmp_path / "gc" / "voron" / "cj1"
        jdir.mkdir(parents=True)
        (jdir / "cube.gcode").write_text("G1")
        api.JOBS["cj1"] = {"id": "cj1", "owner": uid, "state": "started", "created": time.time(), "log": [],
                           "result": {"gcode": str(jdir / "cube.gcode"), "source_file": "cube.stl"},
                           "timelapse": {"state": "recording", "frames": 0}}
        api._bridge_event(bid, uid, "timelapse.state", {"job": "cj1", "state": "rendering", "frames": 42})
        assert api.JOBS["cj1"]["timelapse"] == {"state": "rendering", "frames": 42, "error": None}
        video = (tmp_path / "v.mp4")
        frames = tmp_path / "f"
        frames.mkdir()
        for i in range(1, 6):
            (frames / f"{i:05d}.jpg").write_bytes(jpeg(i))
        tl.render(frames, video)
        bad = c.post("/api/bridge/jobs/cj1/timelapse", content=video.read_bytes(), headers=h)
        assert bad.status_code == 401, "only with the bridge token"
        r = c.post("/api/bridge/jobs/cj1/timelapse", content=video.read_bytes(), headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert api.JOBS["cj1"]["timelapse"]["state"] == "ready"
        got = c.get("/api/jobs/cj1/timelapse", headers=h)
        assert got.status_code == 200 and got.content == video.read_bytes()
        assert c.get("/api/jobs/cj1/timelapse", headers=login(api, c, "ben@example.com")).status_code == 404


def test_always_setting_and_external_prints(tmp_path, monkeypatch):
    import importlib
    import yaml
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"api_token": "t", "work_dir": str(tmp_path / "w"), "gcode_dir": str(tmp_path / "g"),
                                   "printers": [{"id": "cc", "type": "elegoo_sdcp", "host": "127.0.0.1"}]}))
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    h = {"Authorization": "Bearer t"}
    status = {"state": "printing", "file": "orca.gcode", "progress": 3, "layer": 1}

    async def printing(self):
        return status
    monkeypatch.setattr(type(api.get_adapter(api.settings.printer("cc"))), "status", printing)

    async def camera(acct, pid):
        return object()
    monkeypatch.setattr(api, "_camera", camera)
    with TestClient(api.app) as c:
        assert c.get("/api/timelapse/config", headers=h).json() == {"always": False}
        assert not api._timelapse_wanted(None) and api._timelapse_wanted(True)
        # off: the print shows up as a job, without a recording
        asyncio.run(api._track_printer("local", "cc"))
        (job,) = [j for j in api.JOBS.values() if j["kind"] == "external"]
        assert job["state"] == "started" and "timelapse" not in job and api.TIMELAPSE.get(job["id"]) is None
        assert c.post(f"/api/jobs/{job['id']}/send", json={"start": True, "confirm": True}, headers=h).status_code == 409
        api.JOBS.clear()
        # on: stored next to config.yaml, and prints started elsewhere are recorded
        assert c.put("/api/timelapse/config", json={"always": True}, headers=h).json() == {"always": True}
        assert yaml.safe_load((tmp_path / "timelapse.yaml").read_text())["always"] is True
        assert api._timelapse_wanted(None) and not api._timelapse_wanted(False)

        async def track():
            await api._track_printer("local", "cc")
            await asyncio.sleep(0.05)              # the recording is started by a task
        asyncio.run(track())
        (job,) = [j for j in api.JOBS.values() if j["kind"] == "external"]
        rec = api.TIMELAPSE.get(job["id"])
        assert job["timelapse"]["state"] == "recording" and rec.file == "orca.gcode" and rec.seen_active
        assert rec.out == str(tmp_path / "g" / "cc" / job["id"] / "timelapse.mp4")
        asyncio.run(api._track_printer("local", "cc"))
        assert len(api.JOBS) == 1, "seen again: no second job"
