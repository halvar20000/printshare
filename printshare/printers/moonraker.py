"""Klipper printers via the Moonraker HTTP API (e.g. Centauri Carbon with COSMOS).

COSMOS serves Mainsail on port 80 and proxies the Moonraker API there; plain
Moonraker installs listen on 7125. We try the configured URL first, then :7125.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import PrinterConfig


class MoonrakerError(RuntimeError):
    pass


class Moonraker:
    def __init__(self, cfg: PrinterConfig):
        if not cfg.url:
            raise ValueError(f"Printer {cfg.id}: 'url' is required for moonraker (e.g. http://192.168.1.60)")
        self.cfg = cfg
        base = cfg.url.rstrip("/")
        self.candidates = [base]
        u = urlparse(base)
        if u.port is None:
            self.candidates.append(f"{u.scheme}://{u.hostname}:7125")
        self.headers = {"X-Api-Key": cfg.api_key} if cfg.api_key else {}
        self._base: str | None = None

    async def _resolve_base(self, client: httpx.AsyncClient) -> str:
        if self._base:
            return self._base
        errors = []
        for base in self.candidates:
            try:
                r = await client.get(f"{base}/server/info", headers=self.headers)
                if r.status_code == 200 and "result" in r.json():
                    self._base = base
                    return base
                errors.append(f"{base}: HTTP {r.status_code}")
            except (httpx.HTTPError, ValueError) as e:
                errors.append(f"{base}: {e.__class__.__name__}")
        raise MoonrakerError("Moonraker not reachable: " + "; ".join(errors))

    async def send(self, gcode: Path, start: bool = True) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=300) as client:
            base = await self._resolve_base(client)
            with gcode.open("rb") as fh:
                r = await client.post(
                    f"{base}/server/files/upload",
                    headers=self.headers,
                    data={"root": "gcodes", "print": "true" if start else "false"},
                    files={"file": (gcode.name, fh, "application/octet-stream")},
                )
            if r.status_code not in (200, 201):
                raise MoonrakerError(f"Upload failed: HTTP {r.status_code} {r.text[:300]}")
            body = r.json()
            item = (body.get("result") or body).get("item", {})
            return {"uploaded": item.get("path", gcode.name),
                    "started": bool((body.get("result") or body).get("print_started", start))}

    async def status(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            r = await client.get(
                f"{base}/printer/objects/query",
                params={"print_stats": "", "display_status": "", "extruder": "", "heater_bed": "",
                        "virtual_sdcard": ""},
                headers=self.headers,
            )
            if r.status_code != 200:
                raise MoonrakerError(f"Status failed: HTTP {r.status_code}")
            st = r.json()["result"]["status"]
        ps = st.get("print_stats", {})
        info = ps.get("info") or {}
        return {
            "state": ps.get("state"),
            "file": ps.get("filename"),
            "progress": round(100 * (st.get("display_status", {}).get("progress")
                                     or st.get("virtual_sdcard", {}).get("progress") or 0), 1),
            "layer": info.get("current_layer"), "layers": info.get("total_layer"),
            "print_duration_s": ps.get("print_duration"),
            "nozzle": st.get("extruder", {}).get("temperature"),
            "nozzle_target": st.get("extruder", {}).get("target"),
            "bed": st.get("heater_bed", {}).get("temperature"),
            "bed_target": st.get("heater_bed", {}).get("target"),
            "camera": f"{base}/webcam/?action=stream",
        }
