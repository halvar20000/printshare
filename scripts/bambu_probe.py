#!/usr/bin/env python3
"""Check what a Bambu Lab printer allows on the local network (LAN-only mode + developer mode).

Read-only unless --upload is given; it never starts a print.

  python scripts/bambu_probe.py --host 192.168.86.50 --serial 01P00A123456789 \
      --code-file .secrets/bambu-p1s-code [--upload some.gcode.3mf]

1. MQTT over TLS (port 8883, user "bblp", password = access code): subscribe to device/<serial>/report,
   ask for the full state ("pushall") and the firmware versions ("get_version").
2. FTPS with implicit TLS (port 990, same login): list the storage.
3. --upload: put a file into the root of the storage (no print).
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
        ams = (r.get("ams") or {}).get("ams") or []
        for unit in ams:
            for tray in unit.get("tray") or []:
                print(f"  AMS {unit.get('id')} tray {tray.get('id')}: {tray.get('tray_type')} {tray.get('tray_color')} "
                      f"{tray.get('tray_sub_brands') or ''} remain={tray.get('remain')}")
        if r.get("vt_tray"):
            print("  external spool:", r["vt_tray"].get("tray_type"), r["vt_tray"].get("tray_color"))
        if m["info"]:
            print("modules:", [(x.get("name"), x.get("sw_ver")) for x in m["info"].get("module") or []])
        print("report keys:", sorted(r)[:60])
    f = probe_ftps(args.host, code, args.upload)
    print("ftps:", json.dumps(f, default=str)[:800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
