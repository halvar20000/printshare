"""Klipper printers via the Moonraker HTTP API (e.g. Centauri Carbon with COSMOS).

COSMOS serves Mainsail on port 80 and proxies the Moonraker API there; plain
Moonraker installs listen on 7125. We try the configured URL first, then :7125.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from ..camera import Camera
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

    async def send(self, gcode: Path, start: bool = True, leveling: bool | None = None) -> dict[str, Any]:
        # leveling is part of this printer's start G-code; it can't be switched per print here
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

    async def control(self, action: str) -> None:
        if action not in ("pause", "resume", "cancel"):
            raise ValueError(f"unknown action {action!r}")
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            r = await client.post(f"{base}/printer/print/{action}", headers=self.headers)
            if r.status_code != 200:
                raise MoonrakerError(f"{action} failed: HTTP {r.status_code} {r.text[:200]}")

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
            lanes = await self._lanes(client, base)
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
            "lanes": lanes,
        }

    async def camera(self) -> Camera | None:
        """First enabled webcam from Moonraker (crowsnest/ustreamer: MJPEG stream + snapshot)."""
        async with httpx.AsyncClient(timeout=10) as client:
            base = await self._resolve_base(client)
            try:
                r = await client.get(f"{base}/server/webcams/list", headers=self.headers)
                cams = r.json()["result"]["webcams"] if r.status_code == 200 else []
            except (httpx.HTTPError, ValueError, KeyError):
                cams = []
        for cam in cams:
            if cam.get("enabled") is False:
                continue
            service = str(cam.get("service") or "").lower()
            stream = cam.get("stream_url") if "mjpeg" in service or not service else None
            snap = cam.get("snapshot_url")
            if stream or snap:
                return Camera(stream_url=urljoin(base + "/", stream) if stream else None,
                              snapshot_url=urljoin(base + "/", snap) if snap else None,
                              headers=self.headers, name=cam.get("name"))
        return None

    async def _lanes(self, client: httpx.AsyncClient, base: str) -> list[dict[str, Any]]:
        """Filament lanes of an AFC unit (e.g. CANVAS on COSMOS), [] without AFC (spec MA-02).

        AFC (AFCProject/AFC-Klipper-Add-On) reports the lane names in `AFC.lanes`; each lane is its own
        Klipper object ("AFC_lane CANVAS_1", older "AFC_stepper lane1") with map (tool), material, colour, load.
        """
        try:
            r = await client.get(f"{base}/printer/objects/list", headers=self.headers)
            objects = r.json()["result"]["objects"] if r.status_code == 200 else []
            if "AFC" not in objects:
                return []
            r = await client.get(f"{base}/printer/objects/query", params={"AFC": ""}, headers=self.headers)
            afc = r.json()["result"]["status"].get("AFC") or {}
            # one object per lane: "AFC_lane <name>" has the lane data (AFC 1.2); older AFC only has
            # "AFC_stepper <name>". Other objects with the same name (e.g. the unit "AFC_canvas CANVAS_1",
            # "AFC_canvas_lane CANVAS_1") are not lanes - seen on Dominique's COSMOS 2026-09-30.
            available = set(objects)
            lane_objs = []
            for name in afc.get("lanes") or []:
                obj = next((o for o in (f"AFC_lane {name}", f"AFC_stepper {name}") if o in available), None)
                if obj:
                    lane_objs.append(obj)
            if not lane_objs:
                return []
            r = await client.get(f"{base}/printer/objects/query", params={o: "" for o in lane_objs},
                                 headers=self.headers)
            status = r.json()["result"]["status"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return []            # lanes are extra information; the printer status works without them
        current = afc.get("current_load")
        out = []
        for obj in lane_objs:
            ln = status.get(obj) or {}
            name = obj.split(" ", 1)[1]
            m = re.fullmatch(r"T(\d+)", str(ln.get("map") or ""))
            color = str(ln.get("color") or "")
            out.append({
                "id": name,
                "tool": int(m.group(1)) if m else None,
                "unit": ln.get("unit"),
                "material": ln.get("material") or None,
                "color": ("#" + color.lstrip("#")[:6].upper()) if re.fullmatch(r"#?[0-9A-Fa-f]{6,8}", color) else None,
                "filament": ln.get("filament_name") or None,
                "weight_g": ln.get("weight"),
                "loaded": bool(ln.get("prep") or ln.get("load")),
                "in_toolhead": bool(ln.get("tool_loaded")) or name == current,
                "status": ln.get("status"),
            })
        return sorted(out, key=lambda x: (x["tool"] is None, x["tool"] if x["tool"] is not None else 0, x["id"]))
