"""Prusa printers with PrusaLink (MK4/MK4S, MK3.9, CORE One, MINI, XL; MK3S with PrusaLink on a Pi).

API: https://github.com/prusa3d/Prusa-Link-Web/blob/master/spec/openapi.yaml
Auth: HTTP digest with user "maker" and the password shown on the printer (Settings > Network >
PrusaLink); older firmware uses an API key (X-Api-Key) instead.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ..camera import Camera
from ..config import PrinterConfig

# PrusaLink printer states -> the names the rest of PocketPrint3D understands (api.printer_kind)
_STATES = {"IDLE": "standby", "READY": "standby", "BUSY": "busy", "PRINTING": "printing",
           "PAUSED": "paused", "FINISHED": "complete", "STOPPED": "cancelled", "ERROR": "error",
           "ATTENTION": "attention"}


class PrusaLinkError(RuntimeError):
    pass


def remote_name(gcode: Path) -> str:
    """Printer USB drives are FAT: keep names short and plain."""
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", gcode.stem).strip("._") or "print"
    return f"{stem[:60]}{gcode.suffix.lower() or '.gcode'}"


class PrusaLink:
    def __init__(self, cfg: PrinterConfig):
        if not cfg.url:
            raise ValueError(f"Printer {cfg.id}: 'url' is required for prusalink (e.g. http://192.168.1.70)")
        if not (cfg.password or cfg.api_key):
            raise ValueError(f"Printer {cfg.id}: set 'password' (PrusaLink, shown on the printer) or 'api_key'")
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")
        if not re.match(r"^https?://", self.base):
            self.base = "http://" + self.base

    def _client(self, timeout: float = 20) -> httpx.AsyncClient:
        if self.cfg.password:
            return httpx.AsyncClient(timeout=timeout, auth=httpx.DigestAuth(self.cfg.username or "maker", self.cfg.password))
        return httpx.AsyncClient(timeout=timeout, headers={"X-Api-Key": self.cfg.api_key or ""})

    @staticmethod
    def _check(r: httpx.Response, what: str) -> None:
        if r.status_code == 401:
            raise PrusaLinkError(f"{what}: PrusaLink rejected the password / API key")
        if r.status_code == 409:
            raise PrusaLinkError(f"{what}: the printer is busy")
        if r.status_code >= 400:
            raise PrusaLinkError(f"{what} failed: HTTP {r.status_code} {r.text[:200]}")

    async def _storage(self, client: httpx.AsyncClient) -> str:
        r = await client.get(f"{self.base}/api/v1/storage")
        self._check(r, "Storage lookup")
        for st in r.json().get("storage_list") or []:
            if st.get("available") and not st.get("read_only") and st.get("path"):
                return st["path"].strip("/")
        raise PrusaLinkError("No writable storage on the printer - is a USB drive inserted?")

    async def send(self, gcode: Path, start: bool = True, leveling: bool | None = None) -> dict[str, Any]:
        # leveling is part of this printer's start G-code; it can't be switched per print here
        name = remote_name(gcode)
        async with self._client(timeout=600) as client:
            storage = await self._storage(client)
            r = await client.put(
                f"{self.base}/api/v1/files/{storage}/{quote(name)}",
                content=gcode.read_bytes(),
                headers={"Content-Type": "application/octet-stream", "Overwrite": "?1",
                         "Print-After-Upload": "?1" if start else "?0"})
            self._check(r, "Upload")
        return {"uploaded": f"{storage}/{name}", "started": start}

    async def _job_id(self, client: httpx.AsyncClient) -> int:
        r = await client.get(f"{self.base}/api/v1/job")
        if r.status_code == 204:
            raise PrusaLinkError("No print is running")
        self._check(r, "Job lookup")
        return int(r.json()["id"])

    async def control(self, action: str) -> None:
        async with self._client() as client:
            job = await self._job_id(client)
            if action == "pause":
                r = await client.put(f"{self.base}/api/v1/job/{job}/pause")
            elif action == "resume":
                r = await client.put(f"{self.base}/api/v1/job/{job}/resume")
            elif action == "cancel":
                r = await client.delete(f"{self.base}/api/v1/job/{job}")
            else:
                raise ValueError(f"unknown action {action!r}")
            self._check(r, action.capitalize())

    async def controls(self) -> dict[str, Any]:
        # PrusaLink v1 has no API for temperatures, fans or light
        return {"heaters": [], "fans": [], "lights": [], "speed": None, "history": False}

    async def adjust(self, kind: str, target: str, value: Any) -> None:
        raise ValueError("PrusaLink can't be controlled this way")

    async def camera(self) -> Camera | None:
        """PrusaLink cameras (e.g. CORE One): snapshot only; Prusa Connect cameras are not local."""
        async with self._client() as client:
            r = await client.get(f"{self.base}/api/v1/cameras")
            if r.status_code != 200:
                return None
            data = r.json()
        cams = data.get("camera_list") if isinstance(data, dict) else data
        if not cams:
            return None
        auth = httpx.DigestAuth(self.cfg.username or "maker", self.cfg.password) if self.cfg.password else None
        headers = {} if self.cfg.password else {"X-Api-Key": self.cfg.api_key or ""}
        return Camera(snapshot_url=f"{self.base}/api/v1/cameras/snap", auth=auth, headers=headers, name="Prusa")

    async def status(self) -> dict[str, Any]:
        async with self._client() as client:
            r = await client.get(f"{self.base}/api/v1/status")
            self._check(r, "Status")
            st = r.json()
            job: dict[str, Any] = {}
            if st.get("job"):
                jr = await client.get(f"{self.base}/api/v1/job")
                if jr.status_code == 200:
                    job = jr.json()
        pr, sj = st.get("printer") or {}, st.get("job") or {}
        file = (job.get("file") or {})
        progress = sj.get("progress", job.get("progress")) or 0
        return {
            "state": _STATES.get(str(pr.get("state", "")).upper(), str(pr.get("state", "")).lower() or None),
            "file": file.get("display_name") or file.get("name"),
            "progress": round(float(progress), 1),
            "layer": None, "layers": None,
            "print_duration_s": sj.get("time_printing", job.get("time_printing")),
            "time_remaining_s": sj.get("time_remaining", job.get("time_remaining")),
            "nozzle": pr.get("temp_nozzle"), "nozzle_target": pr.get("target_nozzle"),
            "bed": pr.get("temp_bed"), "bed_target": pr.get("target_bed"),
            "heaters": {"nozzle": {"actual": pr.get("temp_nozzle"), "target": pr.get("target_nozzle")},
                        "bed": {"actual": pr.get("temp_bed"), "target": pr.get("target_bed")}},
            "speed": pr.get("speed"),
            "camera": None,
        }
