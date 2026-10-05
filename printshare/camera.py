"""Printer cameras for the app (issue #3, spec DR-06).

The app talks only to PocketPrint3D, also away from home: the server fetches the camera image from the
printer in the LAN and passes it on - as a single (optionally scaled-down) JPEG or as the live MJPEG stream.
Where a camera comes from is decided by the printer adapter (`adapter.camera()` -> Camera | None).
"""
from __future__ import annotations

import asyncio
import io
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

SOI, EOI = b"\xff\xd8", b"\xff\xd9"
MAX_FRAME = 8 * 1024 * 1024
TIMEOUT = 10.0


class CameraError(RuntimeError):
    pass


@dataclass
class Camera:
    stream_url: str | None = None          # MJPEG (multipart/x-mixed-replace)
    snapshot_url: str | None = None        # single JPEG
    headers: dict[str, str] = field(default_factory=dict)
    auth: Any = None                       # httpx auth (PrusaLink digest)
    name: str | None = None
    grab: Callable[[], Awaitable[bytes]] | None = None   # cameras without HTTP (Bambu P1/A1: JPEG over TLS on port 6000)
    rotate: int = 0                        # degrees clockwise (own cameras: "…#rotate=90")

    def info(self) -> dict[str, Any]:
        # a turned picture exists only as stills (the live MJPEG stream is passed through as it is)
        return {"available": True, "stream": bool(self.stream_url) and not self.rotate, "snapshot": True,
                "name": self.name}


def _client(cam: Camera, timeout: float | None = TIMEOUT) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, headers=cam.headers, auth=cam.auth, follow_redirects=True)


async def first_frame(cam: Camera) -> bytes:
    """One JPEG from the stream: SOI (FF D8) up to EOI (FF D9) of the first frame."""
    async with _client(cam) as client, client.stream("GET", cam.stream_url) as r:
        if r.status_code != 200:
            raise CameraError(f"camera stream: HTTP {r.status_code}")
        buf = bytearray()
        start = None
        async for chunk in r.aiter_bytes():
            buf.extend(chunk)
            if start is None:
                i = buf.find(SOI)
                start = i if i >= 0 else None
            if start is not None:
                j = buf.find(EOI, start + 2)
                if j >= 0:
                    return bytes(buf[start:j + 2])
            if len(buf) > MAX_FRAME:
                raise CameraError("camera frame too large")
    raise CameraError("camera stream ended before a complete image arrived")


async def snapshot(cam: Camera) -> bytes:
    jpeg = await _snapshot(cam)
    return await asyncio.to_thread(rotated, jpeg, cam.rotate) if cam.rotate else jpeg


def rotated(jpeg: bytes, degrees: int, quality: int = 85) -> bytes:
    """The picture turned clockwise by 90/180/270 degrees (cameras mounted on their side)."""
    from PIL import Image
    turn = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}.get(degrees)
    if turn is None:
        return jpeg
    with Image.open(io.BytesIO(jpeg)) as im:
        out = io.BytesIO()
        im.convert("RGB").transpose(turn).save(out, "JPEG", quality=quality)
        return out.getvalue()


async def _snapshot(cam: Camera) -> bytes:
    if cam.grab is not None:
        return await cam.grab()
    try:
        if cam.snapshot_url:
            async with _client(cam) as client:
                r = await client.get(cam.snapshot_url)
            if r.status_code == 200 and r.content[:2] == SOI:
                return r.content
            if not cam.stream_url:
                raise CameraError(f"camera snapshot: HTTP {r.status_code}")
        if cam.stream_url:
            return await first_frame(cam)
    except httpx.HTTPError as e:
        raise CameraError(f"camera not reachable: {e.__class__.__name__}") from e
    raise CameraError("this printer has no camera")


def scale(jpeg: bytes, width: int, quality: int = 70) -> bytes:
    """Smaller JPEG for thumbnails and mobile data (the CC1 sends ~1.2 MB frames)."""
    from PIL import Image
    with Image.open(io.BytesIO(jpeg)) as im:
        if im.width <= width:
            return jpeg
        im = im.convert("RGB")
        im.thumbnail((width, width * 4))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=quality, optimize=True)
        return out.getvalue()


async def open_stream(cam: Camera) -> tuple[str, AsyncIterator[bytes], Any]:
    """Start the live stream: (content type incl. boundary, byte iterator, closer)."""
    if not cam.stream_url:
        raise CameraError("this camera has no live stream")
    client = _client(cam, timeout=httpx.Timeout(TIMEOUT, read=None))
    try:
        req = client.build_request("GET", cam.stream_url)
        r = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise CameraError(f"camera not reachable: {e.__class__.__name__}") from e
    if r.status_code != 200:
        await r.aclose()
        await client.aclose()
        raise CameraError(f"camera stream: HTTP {r.status_code}")

    async def close() -> None:
        await r.aclose()
        await client.aclose()

    return r.headers.get("content-type", "multipart/x-mixed-replace"), r.aiter_raw(), close


# ---------- own camera per printer (camera_url): RTSP IP cameras or an HTTP webcam instead of the built-in one ----------
URL_SCHEMES = ("rtsp", "rtsps", "http", "https")
RTSP_TIMEOUT_S = 20
_RTSP_CACHE_S = 2.0
_rtsp_frames: dict[str, tuple[float, bytes]] = {}
_rtsp_locks: dict[str, threading.Lock] = {}


def check_url(url: str) -> str:
    """A camera address the server may open: rtsp(s)://… or http(s)://… with a host. Raises ValueError otherwise."""
    url = (url or "").strip()
    m = re.match(r"^([a-z]+)://([^/?#]+)", url, re.I)
    if not m or m.group(1).lower() not in URL_SCHEMES or len(url) > 500 or any(c in url for c in " \n\r\t"):
        raise ValueError("the camera address must start with rtsp://, rtsps://, http:// or https://")
    return url


def masked(url: str) -> str:
    """The address without user and password, for messages and logs."""
    return re.sub(r"//[^/@]*@", "//", url)


def ffmpeg_frame(source: str, rtsp: bool = True, timeout_s: float = RTSP_TIMEOUT_S) -> bytes:
    """One JPEG from a video source with ffmpeg (the one shipped for time-lapse, imageio-ffmpeg)."""
    from .timelapse import ffmpeg_exe
    exe = ffmpeg_exe()
    if not exe:
        raise CameraError("ffmpeg is missing on the server")
    cmd = [exe, "-hide_banner", "-loglevel", "error"]
    if rtsp:
        cmd += ["-rtsp_transport", "tcp", "-timeout", str(int(timeout_s * 1_000_000))]
    cmd += ["-i", source, "-frames:v", "1", "-q:v", "4", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout_s + 5)
    except subprocess.TimeoutExpired as e:
        raise CameraError("the camera didn't send a picture in time") from e
    if p.returncode != 0 or p.stdout[:2] != SOI:
        err = p.stderr.decode("utf-8", "replace").replace(source, masked(source)).strip().splitlines()
        reason = (err[-1] if err else f"exit {p.returncode}")[:200]
        raise CameraError(f"camera not reachable: {reason}")
    return p.stdout


def rtsp_frame(url: str) -> bytes:
    """Cached for 2 s: thumbnails, time-lapse and failure detection share one connection."""
    lock = _rtsp_locks.setdefault(url, threading.Lock())
    with lock:
        hit = _rtsp_frames.get(url)
        if hit and time.time() - hit[0] < _RTSP_CACHE_S:
            return hit[1]
        jpeg = ffmpeg_frame(url)
        _rtsp_frames[url] = (time.time(), jpeg)
        return jpeg


def external(url: str) -> Camera:
    """An own camera from its address. Options after "#" stay with PocketPrint3D (never sent to the camera):
    "#rotate=90" (or 180, 270) turns the picture clockwise - for a camera mounted on its side."""
    url, _, options = check_url(url).partition("#")
    m = re.search(r"(?:^|&)rotate=(90|180|270)(?:&|$)", options)
    rotate = int(m.group(1)) if m else 0
    if url.lower().startswith("rtsp"):
        return Camera(name="RTSP", grab=lambda: asyncio.to_thread(rtsp_frame, url), rotate=rotate)
    # HTTP: an MJPEG stream (…/stream, ?action=stream, .mjpg) or a single picture (snapshot address)
    if re.search(r"stream|mjpe?g|video", url, re.I):
        return Camera(stream_url=url, name="Webcam", rotate=rotate)
    return Camera(snapshot_url=url, name="Webcam", rotate=rotate)


async def source_for(printer: Any, adapter: Any) -> Camera | None:
    """The camera of a printer: its own camera address if set, else the printer's built-in one."""
    url = getattr(printer, "camera_url", None)
    if url:
        return external(url)
    return await adapter.camera() if hasattr(adapter, "camera") else None
