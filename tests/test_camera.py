"""Printer cameras passed through by the server (issue #3)."""
from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from printshare import camera as cam
from printshare.config import PrinterConfig
from printshare.printers import get_adapter

from .fakes import FakeMoonraker, FakeOctoPrint
from .test_api import H, BackgroundFake, api, client  # noqa: F401 (fixtures)


def run(fake, fn):
    async def go():
        await fake.start()
        try:
            return await fn()
        finally:
            await fake.stop()
    return asyncio.run(go())


def size(jpeg: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(jpeg)).size


def test_moonraker_webcam_from_list():
    ad = get_adapter(PrinterConfig(id="d", type="moonraker", url="http://127.0.0.1:7125"))

    async def go():
        c = await ad.camera()
        return c, await cam.snapshot(c), await cam.first_frame(c)
    c, snap, frame = run(FakeMoonraker(), go)
    assert c.stream_url == "http://127.0.0.1:7125/webcam/?action=stream"
    assert c.snapshot_url == "http://127.0.0.1:7125/webcam/?action=snapshot"
    assert size(snap) == (1280, 720) and size(frame) == (640, 360)


def test_moonraker_without_webcam_and_webrtc_only():
    fake = FakeMoonraker()
    fake.webcams = []
    ad = get_adapter(PrinterConfig(id="d", type="moonraker", url="http://127.0.0.1:7125"))
    assert run(fake, ad.camera) is None
    fake.webcams = [{"name": "w", "enabled": True, "service": "webrtc-camerastreamer",
                     "stream_url": "/webcam/webrtc", "snapshot_url": "/webcam/?action=snapshot"}]
    c = run(fake, ad.camera)
    assert c.stream_url is None and c.snapshot_url.endswith("action=snapshot")   # WebRTC: snapshots only


def test_octoprint_localhost_snapshot_rewritten():
    fake = FakeOctoPrint()
    ad = get_adapter(PrinterConfig(id="o", type="octoprint", url=f"http://127.0.0.1:{fake.port}", api_key="OCTOKEY"))
    c = run(fake, ad.camera)
    assert c.stream_url == f"http://127.0.0.1:{fake.port}/webcam/?action=stream"
    assert c.snapshot_url.startswith(f"http://127.0.0.1:{fake.port}/webcam/")
    snap = run(fake, lambda: cam.snapshot(c))
    assert size(snap) == (320, 240)


def test_scale():
    from .fakes import test_jpeg
    big = test_jpeg(1920, 1080)
    small = cam.scale(big, 640)
    assert size(small) == (640, 360) and len(small) < len(big)
    assert cam.scale(small, 800) == small          # never upscaled


def test_camera_api(api, client, monkeypatch):
    with BackgroundFake(FakeMoonraker()):
        assert client.get("/api/printers/dom/camera/snapshot").status_code == 401
        assert client.get("/api/printers/dom/camera", headers=H).json() == \
            {"available": True, "stream": True, "snapshot": True, "name": "cam"}
        r = client.get("/api/printers/dom/camera/snapshot", headers=H, params={"w": 640})
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and size(r.content) == (640, 360)
        assert r.headers["cache-control"] == "no-store"
        # token in the URL works too (for image views that can't set headers)
        with client.stream("GET", "/api/printers/dom/camera/stream", params={"token": "test-token"}) as s:
            assert s.status_code == 200 and s.headers["content-type"].startswith("multipart/x-mixed-replace")
            data = b"".join(s.iter_bytes())
        assert data.count(b"\xff\xd8") == 3
    # no camera
    fake = FakeMoonraker()
    fake.webcams = []
    with BackgroundFake(fake):
        assert client.get("/api/printers/dom/camera", headers=H).json()["available"] is False
        assert client.get("/api/printers/dom/camera/snapshot", headers=H).status_code == 404
    # printer switched off: a clear 502, not a hanging request
    assert client.get("/api/printers/dom/camera/snapshot", headers=H).status_code == 502


def test_camera_error_messages():
    with pytest.raises(cam.CameraError, match="no camera"):
        asyncio.run(cam.snapshot(cam.Camera()))
