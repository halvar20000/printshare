"""Elegoo Centauri Carbon with stock firmware (SDCP v3 over WebSocket, port 3030).

Uses pycentauri (Apache-2.0, https://github.com/bjan/pycentauri), which has been
verified against real CC1 firmware.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from pycentauri import Printer
from pycentauri.discovery import discover
from pycentauri.models import PrintStatus

from .. import motion
from ..camera import Camera
from ..config import PrinterConfig

log = logging.getLogger("printshare")

# Ack codes of SDCP Cmd 128 (start print)
_START_ACKS = {1: "the printer is busy", 2: "file not found on the printer", 3: "MD5 check failed",
               4: "the printer could not read the file", 5: "resolution mismatch",
               6: "unknown file format", 7: "the file was sliced for a different printer model"}
FILE_TIMEOUT_S = 20      # wait for a fresh upload to show up in the printer's file list
START_TIMEOUT_S = 25     # status pushes arrive every ~5 s


class PrinterStartError(RuntimeError):
    pass


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

    async def send(self, gcode: Path, start: bool = True, leveling: bool | None = None) -> dict[str, Any]:
        async with await self._connect(enable_control=True) as p:
            remote = await p.upload_file(gcode)
            result: dict[str, Any] = {"uploaded": remote, "started": False}
            if start:
                await self._start(p, remote, self.cfg.auto_leveling if leveling is None else leveling)
                result["started"] = True
            return result

    async def _start(self, p: Printer, remote: str, leveling: bool) -> None:
        # Live CC1 V0.3.0-o: a start sent right after the upload is answered with Ack 0 but
        # silently dropped while the printer still processes the new file. So wait for the file
        # to be listed, then check that the printer really leaves idle, and retry once.
        await _wait_for_file(p, remote)
        for attempt in (1, 2):
            resp = await p.start_print(remote, auto_leveling=leveling)
            ack = ((resp.inner or {}).get("Data") or {}).get("Ack")
            if ack not in (0, None):
                raise PrinterStartError(f"The printer refused to start {remote}: "
                                        f"{_START_ACKS.get(ack, f'error code {ack}')}.")
            if await _left_idle(p):
                return
            log.warning("start of %s acknowledged but printer still idle (attempt %d)", remote, attempt)
        raise PrinterStartError(f"The printer accepted the start command but did not start {remote}. "
                                "The file is on the printer; check its screen or start it there.")

    async def control(self, action: str) -> None:
        async with await self._connect(enable_control=True) as p:
            if action == "pause":
                await p.pause()
            elif action == "resume":
                await p.resume()
            elif action == "cancel":
                await p.stop()
            else:
                raise ValueError(f"unknown action {action!r}")

    # ---------- printer control (issue #5): SDCP Cmd 403, verified by pycentauri on V0.3.0-o ----------
    _FANS = {"part": "model", "aux": "auxiliary", "chamber": "chamber"}
    _FAN_KEYS = {"part": "ModelFan", "aux": "AuxiliaryFan", "chamber": "BoxFan"}
    _MAX = {"nozzle": 300, "bed": 110, "chamber": 60}       # pycentauri's safety caps

    async def controls(self) -> dict[str, Any]:
        return {"heaters": [{"id": h, "max": m} for h, m in self._MAX.items()],
                "fans": [{"id": f} for f in self._FANS], "lights": [{"id": "light"}],
                "speed": {"modes": [50, 100, 130, 160]}, "history": False}

    async def adjust(self, kind: str, target: str, value: Any) -> None:
        async with await self._connect(enable_control=True) as p:
            if kind == "heater" and target in self._MAX:
                await p.set_temperatures(**{target: float(value)})
            elif kind == "fan" and target in self._FANS:
                await p.set_fan_speed(**{self._FANS[target]: int(value)})
            elif kind == "light" and target == "light":
                await p.set_light(bool(value))
            elif kind == "speed":
                await p.set_print_speed(int(value))
            else:
                raise ValueError(f"unknown control {kind}/{target}")

    # ---------- moving by hand (0.43.0): SDCP Cmd 401 jog / 402 home, as the printer's own web page does ----------
    def motion(self) -> dict[str, Any]:
        # load / unload: no SDCP command - a tiny G-code file started like a print (motion.filament_gcode)
        return {"home": ["XYZ", "X", "Y", "Z"], "jog": {"axes": ["X", "Y", "Z"], "steps": [0.1, 1, 10, 100]},
                "extrude": False, "load": True, "unload": True, "filament_temp": True, "motors_off": False,
                "macros": [], "filament_as_job": True}

    async def move(self, action: str, axis: str | None = None, distance: float | None = None,
                   macro: str | None = None, temp: int | None = None, slot: int | None = None) -> dict[str, Any]:
        if action in ("load", "unload"):
            t = int(temp or motion.DEFAULT_TEMP)
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / f"{motion.FILE_PREFIX}{action}.gcode"
                path.write_text(motion.filament_gcode(action, t), encoding="utf-8")
                async with await self._connect(enable_control=True) as p:
                    remote = await p.upload_file(path)
                    await self._start(p, remote, False)          # no bed levelling for this
            return {"action": action, "temp": t, "file": remote}
        if action == "home":
            cmd, data = 402, {"Axis": axis}
        elif action == "jog":
            cmd, data = 401, {"Axis": axis, "Step": float(distance)}
        else:
            raise ValueError(f"the Centauri can't {action} from PocketPrint3D")
        async with await self._connect(enable_control=True) as p:
            resp = await p._request(cmd, data, await p.wait_for_mainboard(), timeout=60 if cmd == 402 else 20)
        ack = ((resp.inner or {}).get("Data") or {}).get("Ack")
        if ack not in (0, None):
            raise RuntimeError(f"the printer refused it (error code {ack}) - is it busy or not homed yet?")
        return {"action": action, "axis": axis, "distance": distance}

    async def camera(self) -> Camera:
        # the CC1 serves its webcam as MJPEG on :3031 (pycentauri camera module)
        return Camera(stream_url=f"http://{self.cfg.host}:3031/video", name="Centauri Carbon")

    async def status(self) -> dict[str, Any]:
        async with await self._connect() as p:
            st = await p.status()
        pi = st.print_info
        fans = st.fan_speed or {}
        light = st.light or {}
        out: dict[str, Any] = {
            "nozzle": st.temp_nozzle, "nozzle_target": st.temp_nozzle_target,
            "bed": st.temp_bed, "bed_target": st.temp_bed_target,
            "camera": f"http://{self.cfg.host}:3031/video",
            "heaters": {"nozzle": {"actual": st.temp_nozzle, "target": st.temp_nozzle_target},
                        "bed": {"actual": st.temp_bed, "target": st.temp_bed_target},
                        "chamber": {"actual": st.temp_chamber, "target": st.temp_chamber_target}},
            "fans": {f: fans.get(k) for f, k in self._FAN_KEYS.items() if k in fans},
            "lights": {"light": bool(light.get("SecondLight"))} if "SecondLight" in light else {},
        }
        if pi is not None:
            raw = pi.model_dump() if hasattr(pi, "model_dump") else dict(pi)
            code = raw.get("status")
            out.update({
                "state": _state_name(code),
                "file": raw.get("filename"),
                "progress": raw.get("progress"),
                "layer": raw.get("current_layer"), "layers": raw.get("total_layer"),
                "speed": raw.get("print_speed"),
                "raw": raw,
            })
        return out


# Print states in which nothing is running. After a print the CC1 stays in COMPLETED (9) or
# STOPPED (8) until the next start, so "not idle" alone doesn't prove that a new print started.
_AT_REST = {PrintStatus.IDLE, PrintStatus.STOPPED, PrintStatus.COMPLETED}


def _is_idle(st: Any) -> bool:
    pi = st.print_info
    return (pi is None or pi.status is None or pi.status in _AT_REST) and (st.current_status or [0]) == [0]


async def _left_idle(p: Printer) -> bool:
    end = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < end:
        await asyncio.sleep(2)
        if not _is_idle(await p.status()):
            return True
    return False


async def _wait_for_file(p: Printer, name: str) -> None:
    end = time.monotonic() + FILE_TIMEOUT_S
    while time.monotonic() < end:
        try:
            files = (await p.list_files()).get("file_list", [])
        except Exception:  # noqa: BLE001 - listing is only a readiness hint
            files = []
        if any(f.get("filename") == name for f in files):
            return
        await asyncio.sleep(1)
    log.warning("%s not listed by the printer after %ss, starting anyway", name, FILE_TIMEOUT_S)
