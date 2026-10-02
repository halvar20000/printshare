"""AI failure detection with the Obico ML API (0.23.0): scoring, one-time frame addresses, alert, pause, false alarm."""
from __future__ import annotations

import asyncio
import importlib
import io
import re
from urllib.parse import unquote

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from printshare import failure_watch as fw

JPEG = (lambda b: (Image.new("RGB", (800, 600), (200, 100, 50)).save(b, "JPEG"), b.getvalue())[1])(io.BytesIO())


class FakePrinter:
    def __init__(self):
        self.state, self.file, self.paused = "printing", "benchy.gcode", 0

    async def status(self):
        return {"state": self.state, "file": self.file}

    async def camera(self):
        return object()

    async def control(self, action):
        assert action == "pause"
        self.paused += 1
        self.state = "paused"


class FakeML:
    """Like the real ML API: fetches the image from the given address, answers detections."""
    def __init__(self, watcher):
        self.watcher, self.next, self.fetched = watcher, [], []

    def handler(self, r: httpx.Request) -> httpx.Response:
        assert r.url.path == "/p/"
        img = unquote(r.url.params["img"])
        m = re.fullmatch(r"http://server:8484/api/detect/frame/([\w-]+)\.jpg", img)
        assert m, img
        data = self.watcher.frame(m.group(1))          # the frame is there while the ML API fetches it
        assert data and data[:2] == b"\xff\xd8"
        self.fetched.append(len(data))
        return httpx.Response(200, json={"detections": self.next})


class Printer:
    def __init__(self, pid):
        self.id = pid


@pytest.fixture
def setup(monkeypatch, tmp_path):
    from printshare import camera as cam
    printer = FakePrinter()

    async def snapshot(_):
        return JPEG
    monkeypatch.setattr(cam, "snapshot", snapshot)

    class S:
        cloud, config_dir, printers = False, str(tmp_path), [Printer("cc")]
    kinds = {"printing": "active", "paused": "paused", "complete": "done", "standby": "idle"}
    watcher = fw.FailureWatcher(lambda: S, lambda p: printer, lambda st: kinds.get(st or "", "unknown"))
    ml = FakeML(watcher)
    watcher.http = httpx.AsyncClient(transport=httpx.MockTransport(ml.handler))
    cfg = fw.WatchConfig("http://ml:3333", "", "http://server:8484", 15, "medium", "pause")
    fw.save_config(S, cfg)
    return watcher, printer, ml, S


def test_frame_score():
    assert fw.frame_score([["failure", 0.4, [1, 2, 3, 4]], ["failure", 0.3, [5, 6, 7, 8]], ["nozzle", 0.9, []]]) == 0.7
    assert fw.frame_score([["failure", "x", []], "junk", ["failure"]]) == 0.0
    assert fw.frame_score(None) == 0.0 and fw.frame_score([["failure", 5.0, []]] * 3) == 1.5


def test_warmup_alert_pause_and_new_print(setup):
    watcher, printer, ml, S = setup
    run = lambda: asyncio.run(watcher.tick())          # noqa: E731
    ml.next = [["failure", 0.9, [0, 0, 10, 10]]]
    for _ in range(fw.WARMUP_FRAMES):
        run()
    w = watcher.watches["cc"]
    assert w.alerted_at is None and w.frames == fw.WARMUP_FRAMES and printer.paused == 0   # warm-up: never alert
    assert w.score > 0.8 and ml.fetched and max(ml.fetched) < len(JPEG)                     # scaled to 640 px
    run()
    assert w.alerted_at and printer.paused == 1 and w.public(fw.load_config(S))["state"] == "alert"
    run()                                               # paused: nothing more happens
    assert printer.paused == 1 and w.alerted_at
    printer.state, printer.file = "printing", "next.gcode"   # a new print starts over
    ml.next = []
    run()
    assert w.alerted_at is None and w.frames == 1 and w.print_key == "next.gcode"
    assert not watcher.frames                         # one-time addresses are gone after the check


def test_quiet_print_and_false_alarm(setup):
    watcher, printer, ml, S = setup
    ml.next = [["failure", 0.1, []]]
    for _ in range(fw.WARMUP_FRAMES + 10):
        asyncio.run(watcher.tick())
    assert watcher.watches["cc"].alerted_at is None and printer.paused == 0
    watcher.mute("cc")
    ml.next = [["failure", 1.0, []]]
    for _ in range(20):
        asyncio.run(watcher.tick())
    assert watcher.watches["cc"].alerted_at is None and watcher.state("cc", fw.load_config(S))["state"] == "muted"


def test_ml_api_errors_never_touch_the_print(setup):
    watcher, printer, ml, S = setup
    watcher.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    asyncio.run(watcher.tick())
    w = watcher.watches["cc"]
    assert "HTTP 503" in w.error and "http://server:8484" in w.error and printer.paused == 0 and w.frames == 0


def test_api(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    for k in ("ML_API_URL", "ML_API_TOKEN", "PRINTSHARE_URL"):
        monkeypatch.delenv(k, raising=False)
    api = importlib.reload(importlib.import_module("printshare.api"))
    seen = {}

    def ml(r: httpx.Request) -> httpx.Response:
        token = re.search(r"frame%2F([\w-]+)\.jpg", str(r.url)).group(1)
        seen["frame"] = api.WATCHER.frame(token)
        seen["auth"] = r.headers.get("authorization")
        return httpx.Response(200, json={"detections": []})
    api.WATCHER.http = httpx.AsyncClient(transport=httpx.MockTransport(ml))
    h = {"Authorization": "Bearer t"}
    with TestClient(api.app) as c:
        assert c.get("/api/failure-detection/config", headers=h).json()["configured"] is False
        r = c.put("/api/failure-detection/config", headers=h, json={"ml_url": "http://ml:3333"})
        assert r.status_code == 400 and "server's address" in r.json()["detail"]
        r = c.put("/api/failure-detection/config", headers=h, json={
            "ml_url": "http://ml:3333/", "ml_token": "sec", "server_url": "http://192.168.1.10:8484", "sensitivity": "high", "action": "pause"})
        assert r.status_code == 200, r.text
        assert r.json()["configured"] and r.json()["test"] == {"detections": 0} and r.json()["ml_url"] == "http://ml:3333"
        assert seen["frame"][:2] == b"\xff\xd8" and seen["auth"] == "Bearer sec"
        assert c.get("/api/failure-detection/config", headers=h).json()["token_set"] is True
        assert c.get("/api/detect/frame/does-not-exist-123456.jpg").status_code == 404
        token = api.WATCHER.offer(b"\xff\xd8jpeg")
        assert c.get(f"/api/detect/frame/{token}.jpg").content == b"\xff\xd8jpeg"     # no key needed, token is the secret
        assert c.put("/api/failure-detection/config", headers=h, json={"ml_url": "ftp://x", "server_url": "http://a"}).status_code == 400
        api.WATCHER.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(502)))
        r = c.put("/api/failure-detection/config", headers=h, json={"ml_url": "http://ml:3333", "server_url": "http://x:8484"})
        assert r.status_code == 400 and "can it reach http://x:8484" in r.json()["detail"]
        assert c.delete("/api/failure-detection/config", headers=h).json() == {"configured": False}
