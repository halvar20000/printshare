"""Own camera per printer (camera_url): RTSP IP cameras via ffmpeg, HTTP webcams; overrides the built-in camera."""
from __future__ import annotations

import asyncio
import subprocess

import pytest

from printshare import camera as cam
from printshare.bridge import registry
from printshare.config import PrinterConfig
from printshare.timelapse import ffmpeg_exe


def test_check_url_and_masking():
    assert cam.check_url(" rtsp://u:p@192.168.1.5:554/stream1 ") == "rtsp://u:p@192.168.1.5:554/stream1"
    for bad in ("file:///etc/passwd", "ftp://x/y", "rtsp://", "192.168.1.5", "rtsp://a b/c", "http://x/" + "a" * 600):
        with pytest.raises(ValueError):
            cam.check_url(bad)
    assert cam.masked("rtsp://admin:secret@10.0.0.2:554/s1") == "rtsp://10.0.0.2:554/s1"


def test_kinds_of_cameras():
    assert cam.external("rtsp://10.0.0.2/s1").grab is not None
    assert cam.external("http://10.0.0.2/?action=stream").stream_url
    assert cam.external("http://10.0.0.2/webcam/stream.mjpg").stream_url
    snap = cam.external("http://10.0.0.2/snapshot.jpg")
    assert snap.snapshot_url and not snap.stream_url


class _NoCamera:
    async def camera(self):
        return None


def test_own_camera_wins_over_the_built_in_one():
    with_url = PrinterConfig(id="p", type="bambu_lan", camera_url="rtsp://10.0.0.2/s1")
    assert asyncio.run(cam.source_for(with_url, _NoCamera())).name == "RTSP"
    assert asyncio.run(cam.source_for(PrinterConfig(id="p", type="bambu_lan"), _NoCamera())) is None


@pytest.mark.skipif(not ffmpeg_exe(), reason="no ffmpeg")
def test_ffmpeg_frame_from_a_video(tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x48:d=1",
                    "-pix_fmt", "yuv420p", str(video)], check=True, timeout=60)
    jpeg = cam.ffmpeg_frame(str(video), rtsp=False)
    assert jpeg[:2] == b"\xff\xd8"
    with pytest.raises(cam.CameraError) as e:
        cam.ffmpeg_frame("rtsp://user:secret@127.0.0.1:9/none", timeout_s=3)
    assert "secret" not in str(e.value)               # the camera's password never ends up in a message


def test_bridge_keeps_the_camera_sealed_like_a_password():
    base = registry.build({"type": "bambu_lan", "name": "P1S", "machine": "Bambu Lab P1S 0.4 nozzle"},
                          {"address": "192.168.1.20", "password": "12345678"}, "p1s")
    assert "camera_url" not in base
    with_cam = registry.build({}, {"camera_url": "rtsp://u:p@192.168.1.141/stream1"}, "p1s", base)
    assert with_cam["camera_url"] == "rtsp://u:p@192.168.1.141/stream1" and with_cam["password"] == "12345678"
    kept = registry.build({}, {}, "p1s", with_cam)
    assert kept["camera_url"] == with_cam["camera_url"]
    removed = registry.build({}, {"camera_url": ""}, "p1s", with_cam)
    assert "camera_url" not in removed
    with pytest.raises(ValueError):
        registry.build({}, {"camera_url": "file:///etc/passwd"}, "p1s", base)


def test_rotation_option_stays_with_us(tmp_path):
    import io
    from PIL import Image
    cam_ = cam.external("http://10.0.0.2:8081/#rotate=90")
    assert cam_.snapshot_url == "http://10.0.0.2:8081/" and cam_.rotate == 90       # "#…" is never sent to the camera
    assert cam.external("rtsp://10.0.0.2/s1#rotate=270").rotate == 270
    assert cam.external("http://10.0.0.2/snap.jpg#rotate=45").rotate == 0            # only quarter turns
    assert not cam.external("http://10.0.0.2/stream#rotate=180").info()["stream"]    # turned: stills only
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "red").save(buf, "JPEG")
    out = cam.rotated(buf.getvalue(), 90)
    assert Image.open(io.BytesIO(out)).size == (20, 40)


def test_snapshot_is_turned(monkeypatch):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "blue").save(buf, "JPEG")
    jpeg = buf.getvalue()

    async def grab():
        return jpeg
    c = cam.Camera(grab=grab, rotate=270)
    assert Image.open(io.BytesIO(asyncio.run(cam.snapshot(c)))).size == (20, 40)
    assert asyncio.run(cam.snapshot(cam.Camera(grab=grab))) == jpeg
