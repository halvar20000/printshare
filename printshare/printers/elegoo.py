"""Elegoo Centauri Carbon with stock firmware (SDCP v3 over WebSocket, port 3030).

Uses pycentauri (Apache-2.0, https://github.com/bjan/pycentauri), which has been
verified against real CC1 firmware.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pycentauri import Printer
from pycentauri.discovery import discover
from pycentauri.models import PrintStatus

from ..config import PrinterConfig

_STATES = {v: k.lower() for k, v in vars(PrintStatus).items() if k.isupper() and isinstance(v, int)}


def _state_name(code: int | None) -> str | None:
    return None if code is None else _STATES.get(code, str(code))


class ElegooSDCP:
    def __init__(self, cfg: PrinterConfig):
        if not cfg.host:
            raise ValueError(f"Printer {cfg.id}: 'host' (IP address) is required for elegoo_sdcp")
        self.cfg = cfg
        self._mainboard_id = cfg.mainboard_id

    async def _connect(self, enable_control: bool = False) -> Printer:
        # The printer only pushes its MainboardID over the WebSocket in some states
        # (live CC1 V0.3.0: not even when idle), so ask for it via unicast UDP discovery.
        if not self._mainboard_id:
            try:
                found = await discover(broadcast_address=self.cfg.host, timeout=2.0, retries=2)
            except OSError:
                found = []
            self._mainboard_id = next((f.mainboard_id for f in found if f.host == self.cfg.host), None)
        return await Printer.connect(self.cfg.host, enable_control=enable_control,
                                     mainboard_id=self._mainboard_id)

    async def send(self, gcode: Path, start: bool = True) -> dict[str, Any]:
        async with await self._connect(enable_control=True) as p:
            remote = await p.upload_file(gcode)
            result: dict[str, Any] = {"uploaded": remote, "started": False}
            if start:
                await p.start_print(remote, auto_leveling=self.cfg.auto_leveling)
                result["started"] = True
            return result

    async def status(self) -> dict[str, Any]:
        async with await self._connect() as p:
            st = await p.status()
        pi = st.print_info
        out: dict[str, Any] = {
            "nozzle": st.temp_nozzle, "nozzle_target": st.temp_nozzle_target,
            "bed": st.temp_bed, "bed_target": st.temp_bed_target,
            "camera": f"http://{self.cfg.host}:3031/video",
        }
        if pi is not None:
            raw = pi.model_dump() if hasattr(pi, "model_dump") else dict(pi)
            code = raw.get("status")
            out.update({
                "state": _state_name(code),
                "file": raw.get("filename"),
                "progress": raw.get("progress"),
                "layer": raw.get("current_layer"), "layers": raw.get("total_layer"),
                "raw": raw,
            })
        return out
