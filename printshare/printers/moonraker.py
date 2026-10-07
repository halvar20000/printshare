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

from .. import motion
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

    async def _spoolman(self, client: httpx.AsyncClient, base: str) -> dict[str, Any] | None:
        """Moonraker's own Spoolman link ([spoolman] in moonraker.conf): it books the used filament on the active spool
        itself, so the apps must not book it again. None = not configured."""
        try:
            r = await client.get(f"{base}/server/spoolman/status", headers=self.headers)
            if r.status_code != 200:
                return None
            res = r.json()["result"]
            return {"connected": bool(res.get("spoolman_connected")), "spool_id": res.get("spool_id")}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    async def set_spool(self, spool_id: int | None) -> None:
        """Active Spoolman spool: Moonraker books the filament of the next print on it."""
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            r = await client.post(f"{base}/server/spoolman/spool_id", headers=self.headers, json={"spool_id": spool_id})
            if r.status_code != 200:
                raise MoonrakerError(f"setting the Spoolman spool failed: HTTP {r.status_code} {r.text[:200]}")

    async def control(self, action: str) -> None:
        if action not in ("pause", "resume", "cancel"):
            raise ValueError(f"unknown action {action!r}")
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            r = await client.post(f"{base}/printer/print/{action}", headers=self.headers)
            if r.status_code != 200:
                raise MoonrakerError(f"{action} failed: HTTP {r.status_code} {r.text[:200]}")

    async def _objects(self, client: httpx.AsyncClient, base: str) -> list[str]:
        try:
            r = await client.get(f"{base}/printer/objects/list", headers=self.headers)
            return r.json()["result"]["objects"] if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError, KeyError):
            return []

    async def status(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            objects = await self._objects(client, base)
            ctl = control_objects(objects)
            wanted = {"print_stats", "display_status", "extruder", "heater_bed", "virtual_sdcard", "gcode_move",
                      *ctl["heaters"].values(), *ctl["fans"].values(), *ctl["lights"].values(), *ctl["sensors"].values()}
            r = await client.get(
                f"{base}/printer/objects/query",
                params={o: "" for o in sorted(wanted)},
                headers=self.headers,
            )
            if r.status_code != 200:
                raise MoonrakerError(f"Status failed: HTTP {r.status_code}")
            st = r.json()["result"]["status"]
            lanes = await self._lanes(client, base, objects)
            spoolman = await self._spoolman(client, base)
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
            "spoolman": spoolman,
            **control_status(st, ctl),
        }

    # ---------- printer control (issue #5) ----------
    async def controls(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            ctl = control_objects(await self._objects(client, base))
            limits: dict[str, Any] = {}
            try:     # max temperatures from the Klipper config (e.g. [extruder] max_temp)
                r = await client.get(f"{base}/printer/objects/query", params={"configfile": "settings"},
                                     headers=self.headers)
                limits = r.json()["result"]["status"]["configfile"]["settings"]
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        heaters = []
        for hid, obj in ctl["heaters"].items():
            try:
                mx = float(limits.get(obj.lower(), {}).get("max_temp"))
            except (TypeError, ValueError):
                mx = {"nozzle": 300.0, "bed": 120.0}.get(hid, 80.0)
            heaters.append({"id": hid, "max": mx})
        return {"heaters": heaters, "fans": [{"id": f} for f in ctl["fans"]],
                "lights": [{"id": led} for led in ctl["lights"]], "speed": {"min": 10, "max": 300}, "history": True}

    async def adjust(self, kind: str, target: str, value: Any) -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            ctl = control_objects(await self._objects(client, base))
            if kind == "heater" and target in ctl["heaters"]:
                obj = ctl["heaters"][target]
                script = f"SET_HEATER_TEMPERATURE HEATER={obj.split(' ')[-1]} TARGET={float(value):g}"
            elif kind == "fan" and target in ctl["fans"]:
                pct = max(0, min(100, int(value)))
                if ctl["fans"][target] == "fan":            # part cooling fan: only via M106/M107
                    script = f"M106 S{int(pct * 255 / 100 + 0.5)}" if pct else "M107"
                else:
                    script = f"SET_FAN_SPEED FAN={target} SPEED={pct / 100:g}"
            elif kind == "light" and target in ctl["lights"]:
                v = 1 if value else 0
                script = f"SET_LED LED={target} RED={v} GREEN={v} BLUE={v} WHITE={v}"
            elif kind == "speed":
                script = f"M220 S{int(value)}"
            else:
                raise ValueError(f"unknown control {kind}/{target}")
            r = await client.post(f"{base}/printer/gcode/script", params={"script": script}, headers=self.headers)
            if r.status_code != 200:
                raise MoonrakerError(f"{script} failed: HTTP {r.status_code} {r.text[:200]}")

    # ---------- moving by hand (0.43.0, printshare/motion.py) ----------
    async def motion(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            objects = await self._objects(client, base)
        names = {o.split(" ", 1)[1].strip().upper() for o in objects if o.lower().startswith("gcode_macro ")}
        return {"home": ["XYZ", "X", "Y", "Z"], "jog": {"axes": ["X", "Y", "Z"], "steps": [0.1, 1, 10, 50]},
                "extrude": True, "load": True, "unload": True, "filament_temp": True,
                "motors_off": True, "macros": motion.klipper_macros(objects)}

    async def move(self, action: str, axis: str | None = None, distance: float | None = None,
                   macro: str | None = None, temp: int | None = None, slot: int | None = None) -> dict[str, Any]:
        t = int(temp or motion.DEFAULT_TEMP)

        async def filament_script(name: str) -> str:
            # the printer's own macro when it has one (heated first), else heat + extrude / retract
            async with httpx.AsyncClient(timeout=15) as c:
                objects = await self._objects(c, await self._resolve_base(c))
            has = any(o.strip().upper() == f"GCODE_MACRO {name}" for o in objects)
            return f"M109 S{t}\n{name}" if has else motion.filament_gcode(action, t)
        if action in ("load", "unload"):
            text = await filament_script("LOAD_FILAMENT" if action == "load" else "UNLOAD_FILAMENT")
        script = {"home": lambda: motion.home_gcode(str(axis)),
                  "jog": lambda: motion.jog_gcode(str(axis), float(distance)),
                  "extrude": lambda: motion.extrude_gcode(float(distance)),
                  "load": lambda: text, "unload": lambda: text,
                  "motors_off": lambda: "M84", "macro": lambda: str(macro)}.get(action)
        if script is None:
            raise ValueError(f"unknown action {action!r}")
        # homing, filament routines and macros can take minutes: Moonraker answers when the G-code is done
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=300)) as client:
            base = await self._resolve_base(client)
            r = await client.post(f"{base}/printer/gcode/script", params={"script": script()}, headers=self.headers)
        if r.status_code != 200:
            try:
                msg = r.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                msg = r.text[:200]
            raise MoonrakerError(f"the printer refused it: {msg}")
        return {"action": action, "axis": axis, "distance": distance, "macro": macro}

    async def temperature_history(self) -> dict[str, list]:
        """Moonraker keeps the last ~20 min at 1 s; the app gets every 10th value."""
        async with httpx.AsyncClient(timeout=15) as client:
            base = await self._resolve_base(client)
            ctl = control_objects(await self._objects(client, base))
            r = await client.get(f"{base}/server/temperature_store", headers=self.headers)
            if r.status_code != 200:
                raise MoonrakerError(f"temperature history: HTTP {r.status_code}")
            store = r.json()["result"]
        out: dict[str, list] = {}
        for hid, obj in {**ctl["heaters"], **ctl["sensors"]}.items():
            data = store.get(obj) or {}
            temps, targets = data.get("temperatures") or [], data.get("targets") or []
            if temps:
                n = len(temps)
                idx = range(n - 1, -1, -10)[::-1]                        # every 10th, ending with the newest
                out[hid] = [[i - n + 1, round(temps[i], 1), round(targets[i], 1) if i < len(targets) else None]
                            for i in idx]                           # [seconds before now, actual, target]
        return out

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

    async def _lanes(self, client: httpx.AsyncClient, base: str, objects: list[str]) -> list[dict[str, Any]]:
        """Filament lanes of an AFC unit (e.g. CANVAS on COSMOS), [] without AFC (spec MA-02).

        AFC (AFCProject/AFC-Klipper-Add-On) reports the lane names in `AFC.lanes`; each lane is its own
        Klipper object ("AFC_lane CANVAS_1", older "AFC_stepper lane1") with map (tool), material, colour, load.
        """
        try:
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
                "spool_id": ln.get("spool_id") if isinstance(ln.get("spool_id"), int) else None,
            })
        return sorted(out, key=lambda x: (x["tool"] is None, x["tool"] if x["tool"] is not None else 0, x["id"]))


def control_objects(objects: list[str]) -> dict[str, dict[str, str]]:
    """Klipper objects behind the app's controls: heaters, fans, lights (and a chamber sensor without heater)."""
    have = set(objects)
    heaters = {}
    if "extruder" in have:
        heaters["nozzle"] = "extruder"
    if "heater_bed" in have:
        heaters["bed"] = "heater_bed"
    chamber_heater = next((o for o in objects if o.startswith("heater_generic ") and "chamber" in o.lower()), None)
    if chamber_heater:
        heaters["chamber"] = chamber_heater
    sensors = {}
    chamber_sensor = next((o for o in objects if o.startswith("temperature_sensor ") and "chamber" in o.lower()), None)
    if chamber_sensor and not chamber_heater:
        sensors["chamber"] = chamber_sensor
    fans = {"part": "fan"} if "fan" in have else {}
    fans.update({o.split(" ", 1)[1]: o for o in objects if o.startswith("fan_generic ")})
    lights = {o.split(" ", 1)[1]: o for o in objects if o.split(" ", 1)[0] in ("led", "neopixel", "dotstar")}
    return {"heaters": heaters, "fans": fans, "lights": lights, "sensors": sensors}


def control_status(st: dict[str, Any], ctl: dict[str, dict[str, str]]) -> dict[str, Any]:
    heaters = {hid: {"actual": (st.get(obj) or {}).get("temperature"), "target": (st.get(obj) or {}).get("target")}
               for hid, obj in ctl["heaters"].items()}
    for hid, obj in ctl["sensors"].items():
        heaters[hid] = {"actual": (st.get(obj) or {}).get("temperature"), "target": None}
    fans = {}
    for fid, obj in ctl["fans"].items():
        speed = (st.get(obj) or {}).get("speed")
        fans[fid] = round(speed * 100) if isinstance(speed, (int, float)) else None
    lights = {}
    for lid, obj in ctl["lights"].items():
        data = (st.get(obj) or {}).get("color_data") or []
        lights[lid] = any(any(c > 0 for c in px) for px in data if isinstance(px, list))
    factor = (st.get("gcode_move") or {}).get("speed_factor")
    return {"heaters": heaters, "fans": fans, "lights": lights,
            "speed": round(factor * 100) if isinstance(factor, (int, float)) else None}
