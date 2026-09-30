"""Printer cameras for the app (issue #3, spec DR-06).

The app talks only to PrintShare, also away from home: the server fetches the camera image from the
printer in the LAN and passes it on - as a single (optionally scaled-down) JPEG or as the live MJPEG stream.
Where a camera comes from is decided by the printer adapter (`adapter.camera()` -> Camera | None).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

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

    def info(self) -> dict[str, Any]:
        return {"available": True, "stream": bool(self.stream_url), "snapshot": True, "name": self.name}


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
