#!/usr/bin/env python3
"""Check what a Bambu Lab printer allows on the local network (LAN-only mode + developer mode).

Read-only unless --upload is given; it never starts a print and never moves the AMS.

  python scripts/bambu_probe.py --host 192.168.86.53 --serial 01P00A123456789 \
      --code-file .secrets/bambu-p1s-code [--save p1s-report.json] [--watch 120] [--upload some.gcode.3mf]

1. MQTT over TLS (port 8883, user "bblp", password = access code): subscribe to device/<serial>/report,
   ask for the full state ("pushall") and the firmware versions ("get_version").
2. AMS: every unit and tray decoded (material, colour, remaining %, RFID, humidity, which tray is loaded …).
3. --save: the full report as JSON for test data (serial numbers and network data masked).
4. --watch N: N seconds of live AMS changes - e.g. load or unload a spool at the printer meanwhile.
5. FTPS with implicit TLS (port 990, same login): list the storage. --upload puts a file there (no print).
"""
from __future__ import annotations

import argparse
import ftplib
import json
import socket
import ssl
import sys
import threading
import time
from pathlib import Path


def tls_context() -> ssl.SSLContext:
    # the printer's certificate is signed by Bambu's own CA and names the serial, not the IP
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def probe_mqtt(host: str, serial: str, code: str, wait_s: float) -> dict:
    import paho.mqtt.client as mqtt

    got: dict = {"connected": None, "report": {}, "info": None, "messages": 0}
    done = threading.Event()

    def on_connect(client, userdata, flags, reason, properties=None):
        got["connected"] = str(reason)
        if reason == 0 or getattr(reason, "value", None) == 0:
            client.subscribe(f"device/{serial}/report")
            req = f"device/{serial}/request"
            client.publish(req, json.dumps({"pushing": {"sequence_id": "1", "command": "pushall"}}))
            client.publish(req, json.dumps({"info": {"sequence_id": "2", "command": "get_version"}}))
        else:
            done.set()

    def on_message(client, userdata, msg):
        got["messages"] += 1
        try:
            data = json.loads(msg.payload)
        except ValueError:
            return
        if "print" in data:
            got["report"].update(data["print"])
        if "info" in data and data["info"].get("command") == "get_version":
            got["info"] = data["info"]

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"pp3d-probe-{int(time.time())}")
    client.username_pw_set("bblp", code)
    client.tls_set_context(tls_context())
    client.on_connect, client.on_message = on_connect, on_message
    try:
        client.connect(host, 8883, keepalive=30)
    except OSError as e:
        return {"error": f"MQTT connect failed: {e}"}
    client.loop_start()
    done.wait(wait_s)
    client.loop_stop()
    client.disconnect()
    return got


class ImplicitFTPS(ftplib.FTP_TLS):
    """FTPS with implicit TLS (port 990); the data channel must reuse the TLS session (Bambu firmware)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, context=tls_context(), **kw)
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


def probe_ftps(host: str, code: str, upload: Path | None) -> dict:
    out: dict = {}
    try:
        ftp = ImplicitFTPS()
        ftp.connect(host, 990, timeout=15)
        out["welcome"] = ftp.getwelcome()
        ftp.login("bblp", code)
        ftp.prot_p()
        out["root"] = ftp.nlst()
        if upload:
            with upload.open("rb") as fh:
                out["upload"] = ftp.storbinary(f"STOR {upload.name}", fh)
            out["after_upload"] = upload.name in ftp.nlst()
        ftp.quit()
    except (OSError, ftplib.Error, EOFError) as e:
        out["error"] = f"{e.__class__.__name__}: {e}"
    return out


# ---------- AMS ----------
UNIT_KEYS = ("id", "humidity", "humidity_raw", "temp", "info", "dry_time", "dry_setting", "dry_sf_reason")
TRAY_KEYS = ("tray_type", "tray_sub_brands", "tray_color", "cols", "ctype", "tray_info_idx", "remain", "tray_weight",
             "tray_diameter", "nozzle_temp_min", "nozzle_temp_max", "bed_temp", "bed_temp_type", "tray_temp",
             "tray_time", "k", "n", "cali_idx", "state", "tag_uid", "tray_uuid", "tray_id_name", "xcam_info")
TOP_KEYS = ("ams_exist_bits", "tray_exist_bits", "tray_is_bbl_bits", "tray_read_done_bits", "tray_reading_bits",
            "tray_now", "tray_pre", "tray_tar", "version", "insert_flag", "power_on_flag", "ams_exist_bits_raw")
PRINT_AMS_KEYS = ("ams_status", "ams_rfid_status", "ams_sub_status")


def tray_label(tray_now) -> str:
    """tray_now: 255 = none, 254 = external spool, else unit*4 + tray."""
    try:
        n = int(tray_now)
    except (TypeError, ValueError):
        return str(tray_now)
    return {255: "none", 254: "external spool"}.get(n, f"AMS {n // 4} tray {n % 4}")


def bits(value, count: int = 16) -> str:
    try:
        v = int(str(value), 16)
    except (TypeError, ValueError):
        return str(value)
    return "".join("1" if v >> i & 1 else "." for i in range(count)) + f"  ({value})"


def ams_summary(report: dict) -> list[str]:
    out = []
    ams = report.get("ams") or {}
    for k in TOP_KEYS:
        if k in ams:
            v = ams[k]
            if k.endswith("_bits"):
                v = bits(v)
            elif k in ("tray_now", "tray_pre", "tray_tar"):
                v = f"{v} = {tray_label(v)}"
            out.append(f"  {k}: {v}")
    for k in PRINT_AMS_KEYS:
        if k in report:
            out.append(f"  {k}: {report[k]}")
    for unit in ams.get("ams") or []:
        out.append("  unit " + ", ".join(f"{k}={unit[k]}" for k in UNIT_KEYS if k in unit))
        for tray in unit.get("tray") or []:
            fields = {k: tray[k] for k in TRAY_KEYS if k in tray and tray[k] not in ("", None)}
            other = sorted(set(tray) - set(TRAY_KEYS) - {"id"})
            empty = "" if fields.get("tray_type") else "  (empty)"
            out.append(f"    tray {tray.get('id')}{empty}: {json.dumps(fields, ensure_ascii=False)}"
                       + (f"  other keys: {other}" if other else ""))
    vt = report.get("vt_tray")
    if vt:
        out.append("  external spool: " + json.dumps({k: vt[k] for k in TRAY_KEYS if k in vt and vt[k] not in ("", None)},
                                                     ensure_ascii=False))
    return out


def masked(report: dict, serial: str) -> dict:
    """The report for test data: serial numbers, network and camera addresses removed."""
    def walk(x):
        if isinstance(x, dict):
            return {k: ("<masked>" if k in ("sn", "net", "ipcam", "ip", "mac", "rtsp_url", "wifi_signal", "chip_id") else walk(v))
                    for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str) and serial and serial in x:
            return x.replace(serial, "<serial>")
        return x
    return walk(report)


def watch_ams(host: str, serial: str, code: str, seconds: float) -> None:
    """Live: print what changes in the AMS part of the report (and the loaded tray)."""
    import paho.mqtt.client as mqtt
    last: dict = {}

    def flat(report: dict) -> dict:
        ams = report.get("ams") or {}
        out = {k: ams[k] for k in TOP_KEYS if k in ams}
        out.update({k: report[k] for k in PRINT_AMS_KEYS if k in report})
        for unit in ams.get("ams") or []:
            for k in ("humidity", "temp"):
                if k in unit:
                    out[f"unit{unit.get('id')}.{k}"] = unit[k]
            for tray in unit.get("tray") or []:
                for k in ("tray_type", "tray_color", "remain", "state", "tag_uid"):
                    if k in tray:
                        out[f"unit{unit.get('id')}.tray{tray.get('id')}.{k}"] = tray[k]
        return out

    def on_connect(client, userdata, flags, reason, properties=None):
        client.subscribe(f"device/{serial}/report")
        client.publish(f"device/{serial}/request", json.dumps({"pushing": {"sequence_id": "1", "command": "pushall"}}))

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload).get("print") or {}
        except ValueError:
            return
        now = flat(data)
        changed = {k: v for k, v in now.items() if last.get(k) != v}
        if changed:
            stamp = time.strftime("%H:%M:%S")
            for k, v in sorted(changed.items()):
                shown = f"{v} = {tray_label(v)}" if k in ("tray_now", "tray_pre", "tray_tar") else v
                print(f"{stamp} {k}: {last.get(k)!r} -> {shown!r}")
            last.update(changed)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"pp3d-watch-{int(time.time())}")
    client.username_pw_set("bblp", code)
    client.tls_set_context(tls_context())
    client.on_connect, client.on_message = on_connect, on_message
    client.connect(host, 8883, keepalive=30)
    print(f"watching the AMS for {seconds:.0f} s - load / unload a spool at the printer now if you like")
    client.loop_start()
    time.sleep(seconds)
    client.loop_stop()
    client.disconnect()


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=5):
            return True
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--serial", required=True)
    ap.add_argument("--code-file", required=True, help="file with the access code (never on the command line)")
    ap.add_argument("--upload", type=Path, help="upload this file (no print)")
    ap.add_argument("--wait", type=float, default=8, help="seconds to collect MQTT messages")
    ap.add_argument("--save", type=Path, help="write the full report (masked) as JSON - test data for the adapter")
    ap.add_argument("--watch", type=float, default=0, help="afterwards, show AMS changes live for this many seconds")
    args = ap.parse_args()
    code = Path(args.code_file).read_text(encoding="utf-8").strip()

    print("ports:", {p: port_open(args.host, p) for p in (8883, 990, 6000, 322)})
    m = probe_mqtt(args.host, args.serial, code, args.wait)
    if "error" in m:
        print(m["error"])
    else:
        r = m["report"]
        print("mqtt connect:", m["connected"], "| messages:", m["messages"])
        print("state:", {k: r.get(k) for k in ("gcode_state", "mc_percent", "mc_remaining_time", "gcode_file",
                                                "subtask_name", "nozzle_temper", "nozzle_target_temper",
                                                "bed_temper", "bed_target_temper", "nozzle_diameter", "lights_report")})
        print("AMS:")
        lines = ams_summary(r)
        print("\n".join(lines) if lines else "  (no AMS data in the report)")
        if m["info"]:
            print("modules:", [(x.get("name"), x.get("sw_ver")) for x in m["info"].get("module") or []])
        print("report keys:", sorted(r))
        if args.save:
            args.save.write_text(json.dumps({"print": masked(r, args.serial), "info": masked(m["info"] or {}, args.serial)},
                                            indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"saved the full report to {args.save} (serial / network masked)")
    f = probe_ftps(args.host, code, args.upload)
    print("ftps:", json.dumps(f, default=str)[:800])
    if args.watch > 0 and "error" not in m:
        watch_ams(args.host, args.serial, code, args.watch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
