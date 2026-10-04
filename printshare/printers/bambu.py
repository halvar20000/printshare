"""Bambu Lab printers in LAN-only mode with developer mode (P1S, P1P, X1C, A1 …; docs/BRIDGE.md section 8).

Checked on Thomas' P1S (firmware 01.09.01.00, 2026-10-04) with scripts/bambu_probe.py:
- MQTT over TLS on port 8883, user "bblp", password = the access code shown on the printer. The printer is the broker.
  Reports arrive on `device/<serial>/report`, commands go to `device/<serial>/request`. The P1 series sends only what
  changed, so one connection per printer stays open and merges the reports (a full report is asked for once on
  connect with "pushall" - Bambu advises against asking for it often on the P1).
- FTPS with implicit TLS on port 990, same login; the root is the printer's SD card.
- The serial number is the CN of the printer's TLS certificate (issuer "BBL CA"), so the user never types it.

Printing: the G-code is wrapped in a minimal ".gcode.3mf" (Metadata/plate_1.gcode + md5), uploaded by FTPS and
started with the "project_file" command - the way Bambu Studio sends a sliced plate. The AMS trays are the lanes; the
tray per filament goes into `ams_mapping` instead of rewriting the G-code.
"""
from __future__ import annotations

import asyncio
import ftplib
import hashlib
import io
import json
import logging
import re
import socket
import ssl
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from ..camera import Camera
from ..config import PrinterConfig
from .. import gcode_info

log = logging.getLogger(__name__)

MQTT_PORT, FTPS_PORT = 8883, 990
USER = "bblp"
READY_TIMEOUT_S = 8.0
# after "project_file": the printer must start preparing within this time (seen: ~1-5 s on a P1S). Without LAN-only
# mode it ignores the command silently (P1S FW 01.08.01.00 and 01.09.01.00, 2026-10-04) - the app must not show "started"
START_TIMEOUT_S = 45.0
_STARTING = ("PREPARE", "SLICING", "RUNNING")

# gcode_state → the names the rest of PocketPrint3D understands (api.printer_kind)
_STATES = {"IDLE": "standby", "PREPARE": "printing", "SLICING": "printing", "RUNNING": "printing",
           "PAUSE": "paused", "FINISH": "complete", "FAILED": "error"}
# print_error codes that mean "stopped by the user" (HMS 0300-400C "the task was cancelled")
_CANCELLED = {50348044}
# print_speed levels 1-4 (silent, standard, sport, ludicrous) in percent
SPEED_LEVELS = {1: 50, 2: 100, 3: 124, 4: 166}
# fans as Bambu numbers them in M106 P<n> and report them (0-15)
_FANS = {"part": (1, "cooling_fan_speed"), "aux": (2, "big_fan1_speed"), "chamber": (3, "big_fan2_speed")}
_HEATERS = {"nozzle": ("M104", 300), "bed": ("M140", 110)}
# serial number prefixes → model and OrcaSlicer machine preset (0.4 nozzle)
MODELS = {"01P": "P1S", "01S": "P1P", "00M": "X1 Carbon", "03W": "X1E", "030": "A1 mini", "039": "A1",
          "22E": "P2S", "094": "H2D"}


class BambuError(RuntimeError):
    pass


def tls_context() -> ssl.SSLContext:
    # the certificate is signed by Bambu's own CA and names the serial, not the IP address
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def read_serial(host: str, timeout: float = 5.0) -> tuple[str | None, bool]:
    """(serial from the TLS certificate, is it a Bambu printer) - CN = serial, issuer "BBL CA"."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    try:
        with socket.create_connection((host, MQTT_PORT), timeout=timeout) as raw:
            with tls_context().wrap_socket(raw) as s:
                der = s.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError):
        return None, False
    if not der:
        return None, False
    cert = x509.load_der_x509_certificate(der)
    issuer = " ".join(a.value for a in cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME))
    cn = [a.value for a in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)]
    is_bambu = "BBL" in issuer or "Bambu" in issuer
    serial = str(cn[0]) if cn and re.fullmatch(r"[0-9A-Z]{8,20}", str(cn[0])) else None
    return serial, is_bambu


def model_for(serial: str | None) -> str | None:
    return next((m for p, m in MODELS.items() if serial and serial.startswith(p)), None)


def machine_for(serial: str | None) -> str | None:
    """OrcaSlicer machine preset for this printer (0.4 nozzle), e.g. "Bambu Lab P1S 0.4 nozzle"."""
    m = model_for(serial)
    return f"Bambu Lab {m} 0.4 nozzle" if m else None


def merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Merge a (partial) P1 report into the kept state; lists of dicts with "id" (AMS units, trays) by id."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        elif isinstance(v, list) and isinstance(dst.get(k), list) and v and all(isinstance(x, dict) and "id" in x for x in v):
            by_id = {str(x.get("id")): x for x in dst[k] if isinstance(x, dict)}
            for item in v:
                old = by_id.get(str(item["id"]))
                if old is None:
                    dst[k].append(item)
                else:
                    merge(old, item)
        else:
            dst[k] = v


# ---------- what the report means ----------
def _color(c: Any) -> str | None:
    c = str(c or "")
    return "#" + c[:6].upper() if re.fullmatch(r"[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", c) and c[6:8] != "00" else None


def lanes(report: dict[str, Any]) -> list[dict[str, Any]]:
    """AMS trays as lanes (same shape as AFC lanes, printers/moonraker.py): id "A1".."A4" ("B1".. for a 2nd AMS),
    tool = tray number across all units (0-15) as Bambu counts it in ams_mapping / tray_now."""
    ams = report.get("ams") or {}
    exist = int(str(ams.get("tray_exist_bits") or "0"), 16)
    now = str(ams.get("tray_now") or "255")
    out = []
    for unit in ams.get("ams") or []:
        try:
            u = int(unit.get("id"))
        except (TypeError, ValueError):
            continue
        for tray in unit.get("tray") or []:
            try:
                t = int(tray.get("id"))
            except (TypeError, ValueError):
                continue
            tool = u * 4 + t
            inserted = bool(exist >> tool & 1)
            remain = tray.get("remain")
            try:
                weight = float(tray.get("tray_weight") or 0)
            except (TypeError, ValueError):
                weight = 0.0
            out.append({
                "id": f"{chr(65 + u)}{t + 1}",
                "tool": tool,
                "unit": f"AMS {u + 1}",
                "material": (tray.get("tray_type") or None) if inserted else None,
                "color": _color(tray.get("tray_color")) if inserted else None,
                "filament": (tray.get("tray_sub_brands") or None) if inserted else None,
                "weight_g": round(weight * remain / 100) if inserted and weight and isinstance(remain, int) and remain >= 0 else None,
                "remain_pct": remain if inserted and isinstance(remain, int) and remain >= 0 else None,
                "loaded": inserted,
                "in_toolhead": now == str(tool),
                "status": "ready" if inserted else "empty",
                "spool_id": None,
            })
    return sorted(out, key=lambda x: x["tool"])


def status_from(report: dict[str, Any]) -> dict[str, Any]:
    state = str(report.get("gcode_state") or "").upper()
    norm = _STATES.get(state, state.lower() or None)
    if state == "FAILED" and int(report.get("print_error") or 0) in _CANCELLED | {0}:
        norm = "cancelled"
    remaining = report.get("mc_remaining_time")
    lights = {x.get("node"): x.get("mode") == "on" for x in report.get("lights_report") or [] if isinstance(x, dict)}
    fans = {}
    for fid, (_, key) in _FANS.items():
        try:
            fans[fid] = round(int(report[key]) * 100 / 15) if key in report else None
        except (TypeError, ValueError):
            fans[fid] = None
    file = report.get("subtask_name") or Path(str(report.get("gcode_file") or "")).name or None
    return {
        "state": norm,
        "file": file,
        "progress": float(report.get("mc_percent") or 0),
        "layer": report.get("layer_num"), "layers": report.get("total_layer_num"),
        "time_remaining_s": int(remaining) * 60 if isinstance(remaining, (int, float)) and remaining >= 0 else None,
        "nozzle": report.get("nozzle_temper"), "nozzle_target": report.get("nozzle_target_temper"),
        "bed": report.get("bed_temper"), "bed_target": report.get("bed_target_temper"),
        "heaters": {"nozzle": {"actual": report.get("nozzle_temper"), "target": report.get("nozzle_target_temper")},
                    "bed": {"actual": report.get("bed_temper"), "target": report.get("bed_target_temper")}},
        "fans": fans,
        "lights": {"light": lights.get("chamber_light", False)},
        "speed": SPEED_LEVELS.get(int(report.get("spd_lvl") or 2), None),
        "lanes": lanes(report),
        "camera": None,
        "error": report.get("print_error") or None,
    }


def ams_mapping(gcode: Path, tools: dict[int, int] | None, report: dict[str, Any]) -> list[int]:
    """Tray per filament of the G-code: the choice from the app (lanes), else the tray in the toolhead for a single
    filament, else filament n → tray n."""
    n = max(1, len(gcode_info.orca_settings(gcode).get("types") or []))
    loaded = str((report.get("ams") or {}).get("tray_now") or "255")
    out = []
    for i in range(n):
        if tools and i in tools:
            out.append(int(tools[i]))
        elif n == 1 and loaded.isdigit() and int(loaded) < 16:
            out.append(int(loaded))
        else:
            out.append(i)
    return out


def wrap_3mf(gcode: Path, name: str) -> bytes:
    """A minimal sliced 3MF around one plate of G-code - what the printer opens with "project_file"."""
    data = gcode.read_bytes()
    info = gcode_info.orca_settings(gcode)
    filaments = "".join(
        f'    <filament id="{i + 1}" type="{t}" color="{(info.get("colours") or [None] * 99)[i] or "#FFFFFF"}" />\n'
        for i, t in enumerate(info.get("types") or ["PLA"]))
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/'
                               'package/2006/content-types">\n <Default Extension="rels" ContentType="application/vnd.'
                               'openxmlformats-package.relationships+xml"/>\n <Default Extension="model" ContentType='
                               '"application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n <Default Extension="gcode" '
                               'ContentType="text/x.gcode"/>\n</Types>\n',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/'
                       'package/2006/relationships">\n <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://'
                       'schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n',
        "3D/3dmodel.model": '<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns='
                            '"http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n <metadata name="Application">'
                            'PocketPrint3D</metadata>\n <resources/>\n <build/>\n</model>\n',
        "Metadata/slice_info.config": f'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <plate>\n    <metadata key='
                                      f'"index" value="1"/>\n{filaments}  </plate>\n</config>\n',
        "Metadata/plate_1.gcode": data,
        "Metadata/plate_1.gcode.md5": hashlib.md5(data).hexdigest().upper(),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, content in files.items():
            z.writestr(fname, content)
    return buf.getvalue()


def remote_name(gcode: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", gcode.stem).strip("._") or "print"
    return f"{stem[:60]}.gcode.3mf"


# ---------- connection ----------
class BambuLink:
    """One MQTT connection per printer (paho's own thread), the merged report, and commands."""

    def __init__(self, host: str, serial: str, code: str) -> None:
        import paho.mqtt.client as mqtt
        self.host, self.serial, self.code = host, serial, code
        self.report: dict[str, Any] = {}
        self.info: dict[str, Any] = {}
        self.ready = threading.Event()
        self.error: str | None = None
        self.last_message = 0.0
        self.lock = threading.Lock()
        self.replies: dict[str, dict[str, Any]] = {}       # last answer per command, e.g. "project_file"
        self._seq = 0
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"pp3d-{serial[-6:]}-{int(time.time()) % 100000}")
        c.username_pw_set(USER, code)
        c.tls_set_context(tls_context())
        c.reconnect_delay_set(2, 30)
        c.on_connect, c.on_message, c.on_disconnect = self._on_connect, self._on_message, self._on_disconnect
        self.client = c
        c.connect_async(host, MQTT_PORT, keepalive=30)
        c.loop_start()

    def _on_connect(self, client, userdata, flags, reason, properties=None) -> None:
        if getattr(reason, "is_failure", False):
            self.error = "the printer refused the access code" if "authori" in str(reason).lower() else str(reason)
            log.warning("Bambu %s: %s", self.host, self.error)
            return
        self.error = None
        client.subscribe(f"device/{self.serial}/report")
        self.publish({"pushing": {"command": "pushall"}})
        self.publish({"info": {"command": "get_version"}})

    def _on_disconnect(self, client, userdata, flags, reason, properties=None) -> None:
        self.ready.clear()

    def _on_message(self, client, userdata, msg) -> None:
        try:
            data = json.loads(msg.payload)
        except ValueError:
            return
        self.last_message = time.time()
        if isinstance(data.get("print"), dict):
            cmd = data["print"].get("command")
            if cmd and cmd not in ("push_status",):
                self.replies[str(cmd)] = {**data["print"], "_at": time.time()}
            with self.lock:
                merge(self.report, data["print"])
            if "gcode_state" in self.report:
                self.ready.set()
        if isinstance(data.get("info"), dict) and data["info"].get("command") == "get_version":
            self.info = data["info"]

    def publish(self, payload: dict[str, Any]) -> None:
        self._seq += 1
        for section in payload.values():
            if isinstance(section, dict):
                section.setdefault("sequence_id", str(self._seq))
        self.client.publish(f"device/{self.serial}/request", json.dumps(payload))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.report))

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


_LINKS: dict[tuple[str, str], BambuLink] = {}
_LINKS_LOCK = threading.Lock()


def link(host: str, serial: str, code: str) -> BambuLink:
    with _LINKS_LOCK:
        lk = _LINKS.get((host, serial))
        if lk is not None and lk.code != code:            # access code changed on the printer / in the app
            lk.close()
            lk = None
        if lk is None:
            lk = _LINKS[(host, serial)] = BambuLink(host, serial, code)
        return lk


class _FTPS(ftplib.FTP_TLS):
    """Implicit TLS (port 990); the data channel reuses the TLS session (the printer insists)."""

    def __init__(self) -> None:
        super().__init__(context=tls_context())
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, session=self.sock.session)
        return conn, size

    def storbinary(self, cmd, fp, blocksize=65536, callback=None, rest=None):
        # like ftplib's, without the TLS shutdown of the data channel: the printer never answers it (seen on a P1S,
        # the upload then times out although the file arrived)
        self.voidcmd("TYPE I")
        with self.transfercmd(cmd, rest) as conn:
            while buf := fp.read(blocksize):
                conn.sendall(buf)
                if callback:
                    callback(buf)
        return self.voidresp()


def upload(host: str, code: str, name: str, data: bytes) -> None:
    ftp = _FTPS()
    try:
        ftp.connect(host, FTPS_PORT, timeout=30)
        ftp.login(USER, code)
        ftp.prot_p()
        ftp.storbinary(f"STOR {name}", io.BytesIO(data))
    except (OSError, ftplib.Error, EOFError) as e:
        raise BambuError(f"Upload to the printer failed: {e} - is an SD card in the printer?") from e
    finally:
        try:
            ftp.quit()
        except (OSError, ftplib.Error, EOFError, AttributeError):
            ftp.close()


class Bambu:
    maps_tools = True          # lanes go into ams_mapping, the G-code stays as sliced (pipeline.send_job)

    def __init__(self, cfg: PrinterConfig):
        host = (cfg.host or re.sub(r"^https?://", "", cfg.url or "").split("/")[0].split(":")[0]).strip()
        if not host:
            raise ValueError(f"Printer {cfg.id}: 'host' (the printer's IP address) is required for bambu_lan")
        if not cfg.password:
            raise ValueError(f"Printer {cfg.id}: 'password' = the access code shown on the printer is required")
        self.cfg, self.host, self.code = cfg, host, cfg.password
        self._serial = cfg.serial

    async def _link(self) -> BambuLink:
        if not self._serial:
            serial, is_bambu = await asyncio.to_thread(read_serial, self.host)
            if not serial:
                raise BambuError("The printer doesn't answer on port 8883 - is it on, in LAN-only mode with "
                                 "developer mode?" if not is_bambu else "Couldn't read the printer's serial number")
            self._serial = serial
        lk = link(self.host, self._serial, self.code)
        if not lk.ready.is_set():
            await asyncio.to_thread(lk.ready.wait, READY_TIMEOUT_S)
        if lk.error:
            raise BambuError(lk.error)
        if not lk.ready.is_set():
            raise BambuError("No answer from the printer - is it on, in LAN-only mode with developer mode?")
        return lk

    async def status(self) -> dict[str, Any]:
        lk = await self._link()
        return status_from(lk.snapshot())

    async def send(self, gcode: Path, start: bool = True, leveling: bool | None = None,
                   tools: dict[int, int] | None = None) -> dict[str, Any]:
        lk = await self._link()
        name = remote_name(gcode)
        data = await asyncio.to_thread(wrap_3mf, gcode, name)
        await asyncio.to_thread(upload, self.host, self.code, name, data)
        out: dict[str, Any] = {"uploaded": name, "file": gcode.name, "started": False}
        if not start:
            return out
        report = lk.snapshot()
        mapping = ams_mapping(gcode, tools, report)
        has_ams = int(str((report.get("ams") or {}).get("ams_exist_bits") or "0"), 16) > 0
        sent_at = time.time()
        lk.publish({"print": {
            "command": "project_file", "param": "Metadata/plate_1.gcode", "url": f"file:///sdcard/{name}",
            "file": name, "md5": "", "subtask_name": gcode.stem, "project_id": "0", "profile_id": "0", "task_id": "0",
            "subtask_id": "0", "bed_type": "auto", "timelapse": False, "bed_leveling": leveling is not False,
            "bed_levelling": leveling is not False, "flow_cali": False, "vibration_cali": False, "layer_inspect": False,
            "use_ams": has_ams, "ams_mapping": mapping if has_ams else [],
        }})
        await self._await_start(lk, gcode.stem, sent_at)
        return {**out, "started": True, "ams_mapping": mapping if has_ams else []}

    async def _await_start(self, lk: BambuLink, task: str, sent_at: float) -> None:
        """The printer has to show that it starts this print; a refusal or silence becomes a clear error."""
        deadline = sent_at + START_TIMEOUT_S
        while time.time() < deadline:
            reply = lk.replies.get("project_file")
            if reply and reply.get("_at", 0) >= sent_at and str(reply.get("result", "")).lower() in ("fail", "failed", "error"):
                reason = reply.get("reason") or reply.get("err_code") or "refused"
                raise BambuError(f"The printer refused the print ({reason}) - is LAN-only mode with developer mode on?")
            st = lk.snapshot()
            if str(st.get("gcode_state") or "").upper() in _STARTING and st.get("subtask_name") in (task, None, ""):
                return
            await asyncio.sleep(1)
        raise BambuError("The printer didn't start the print. Switch on LAN-only mode and developer mode on the printer "
                         "(Settings → WLAN) - without them Bambu printers take no print jobs from other apps.")

    async def control(self, action: str) -> None:
        if action not in ("pause", "resume", "cancel"):
            raise ValueError(f"unknown action {action!r}")
        lk = await self._link()
        lk.publish({"print": {"command": "stop" if action == "cancel" else action, "param": ""}})

    async def controls(self) -> dict[str, Any]:
        return {"heaters": [{"id": k, "max": mx} for k, (_, mx) in _HEATERS.items()],
                "fans": [{"id": k} for k in _FANS], "lights": [{"id": "light"}],
                "speed": {"modes": list(SPEED_LEVELS.values())}, "history": False}

    async def adjust(self, kind: str, target: str, value: Any) -> None:
        lk = await self._link()
        if kind == "heater" and target in _HEATERS:
            cmd, mx = _HEATERS[target]
            lk.publish({"print": {"command": "gcode_line", "param": f"{cmd} S{max(0, min(mx, int(value)))}\n"}})
        elif kind == "fan" and target in _FANS:
            pwm = round(max(0, min(100, float(value))) * 255 / 100)
            lk.publish({"print": {"command": "gcode_line", "param": f"M106 P{_FANS[target][0]} S{pwm}\n"}})
        elif kind == "light" and target == "light":
            lk.publish({"system": {"command": "ledctrl", "led_node": "chamber_light", "led_mode": "on" if value else "off",
                                   "led_on_time": 500, "led_off_time": 500, "loop_times": 0, "interval_time": 0}})
        elif kind == "speed":
            level = next((lv for lv, pct in SPEED_LEVELS.items() if pct == int(value)), None)
            if level is None:
                raise ValueError(f"speed must be one of {list(SPEED_LEVELS.values())}")
            lk.publish({"print": {"command": "print_speed", "param": str(level)}})
        else:
            raise ValueError(f"can't adjust {kind} {target!r}")

    async def camera(self) -> Camera | None:
        return None            # port 6000 (JPEG over TLS) comes with the next step
