"""OctoPrint (https://docs.octoprint.org/en/master/api/) - covers many printers driven by a Raspberry Pi,
e.g. Creality Ender, Prusa MK3S, Anycubic i3. Auth: API key (OctoPrint settings > Application keys)."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Any

import httpx

from ..camera import Camera
from ..config import PrinterConfig


class OctoPrintError(RuntimeError):
    pass


def _state(printer: dict[str, Any] | None, job: dict[str, Any]) -> str:
    """OctoPrint flags / state text -> the names the rest of PrintShare understands."""
    if printer is None:
        return "offline"
    flags = (printer.get("state") or {}).get("flags") or {}
    if flags.get("cancelling"):
        return "stopping"
    if flags.get("pausing"):
        return "pausing"
    if flags.get("paused"):
        return "paused"
    if flags.get("printing"):
        return "printing"
    if flags.get("error") or flags.get("closedOrError"):
        return "error"
    if ((job.get("progress") or {}).get("completion") or 0) >= 100:
        return "complete"
    return "standby"


class OctoPrint:
    def __init__(self, cfg: PrinterConfig):
        if not cfg.url:
            raise ValueError(f"Printer {cfg.id}: 'url' is required for octoprint (e.g. http://octopi.local)")
        if not cfg.api_key:
            raise ValueError(f"Printer {cfg.id}: 'api_key' is required for octoprint (Settings > Application keys)")
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")
        if not re.match(r"^https?://", self.base):
            self.base = "http://" + self.base

    def _client(self, timeout: float = 20) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, headers={"X-Api-Key": self.cfg.api_key or ""})

    @staticmethod
    def _check(r: httpx.Response, what: str) -> None:
        if r.status_code in (401, 403):
            raise OctoPrintError(f"{what}: OctoPrint rejected the API key")
        if r.status_code == 409:
            raise OctoPrintError(f"{what}: the printer is busy or not connected in OctoPrint")
        if r.status_code >= 400:
            raise OctoPrintError(f"{what} failed: HTTP {r.status_code} {r.text[:200]}")

    async def send(self, gcode: Path, start: bool = True, leveling: bool | None = None) -> dict[str, Any]:
        # leveling is part of this printer's start G-code; it can't be switched per print here
        async with self._client(timeout=600) as client:
            with gcode.open("rb") as fh:
                r = await client.post(
                    f"{self.base}/api/files/local",
                    files={"file": (gcode.name, fh, "application/octet-stream")},
                    data={"select": "true" if start else "false", "print": "true" if start else "false"})
            self._check(r, "Upload")
            body = r.json() if r.content else {}
        if start and body.get("effectivePrint") is False:
            raise OctoPrintError("OctoPrint stored the file but did not start it - is the printer connected?")
        name = ((body.get("files") or {}).get("local") or {}).get("name") or gcode.name
        return {"uploaded": name, "started": start}

    async def control(self, action: str) -> None:
        body = {"pause": {"command": "pause", "action": "pause"},
                "resume": {"command": "pause", "action": "resume"},
                "cancel": {"command": "cancel"}}.get(action)
        if body is None:
            raise ValueError(f"unknown action {action!r}")
        async with self._client() as client:
            r = await client.post(f"{self.base}/api/job", json=body)
            self._check(r, action.capitalize())

    async def camera(self) -> Camera | None:
        """Webcam from OctoPrint's settings; URLs may be relative or point to 127.0.0.1 of the Pi."""
        async with self._client() as client:
            r = await client.get(f"{self.base}/api/settings")
            self._check(r, "Camera")
            web = (r.json().get("webcam") or {})
        if web.get("webcamEnabled") is False:
            return None
        host = urlparse(self.base).hostname or ""

        def fix(url: str | None) -> str | None:
            if not url:
                return None
            u = urlparse(urljoin(self.base + "/", url))
            if u.hostname in ("127.0.0.1", "localhost"):
                u = u._replace(netloc=host + (f":{u.port}" if u.port else ""))
            return u.geturl()

        stream, snap = fix(web.get("streamUrl")), fix(web.get("snapshotUrl"))
        if not (stream or snap):
            return None
        return Camera(stream_url=stream, snapshot_url=snap, name="OctoPrint")

    async def status(self) -> dict[str, Any]:
        async with self._client() as client:
            jr = await client.get(f"{self.base}/api/job")
            self._check(jr, "Status")
            job = jr.json()
            pr = await client.get(f"{self.base}/api/printer")
            if pr.status_code == 409:  # OctoPrint runs, but the printer is not connected
                printer = None
            else:
                self._check(pr, "Status")
                printer = pr.json()
        temps = (printer or {}).get("temperature") or {}
        tool, bed = temps.get("tool0") or {}, temps.get("bed") or {}
        progress = (job.get("progress") or {})
        file = ((job.get("job") or {}).get("file") or {})
        return {
            "state": _state(printer, job),
            "file": file.get("display") or file.get("name"),
            "progress": round(float(progress.get("completion") or 0), 1),
            "layer": None, "layers": None,
            "print_duration_s": progress.get("printTime"),
            "time_remaining_s": progress.get("printTimeLeft"),
            "nozzle": tool.get("actual"), "nozzle_target": tool.get("target"),
            "bed": bed.get("actual"), "bed_target": bed.get("target"),
            "camera": f"{self.base}/webcam/?action=stream",
        }
