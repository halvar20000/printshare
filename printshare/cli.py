"""Command line: `printshare print <link> --printer cc-thomas` etc."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from .config import JobOptions, load_settings
from .fetch import FetchError, Fetcher
from .pipeline import run_job
from .printers import get_adapter
from .slicer import Slicer


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="printshare", description="Print Printables/Thingiverse models on your printer")
    ap.add_argument("--config", help="path to config.yaml (default /config/config.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("print", help="download, slice, upload and start")
    p.add_argument("link")
    p.add_argument("--printer", "-p")
    p.add_argument("--file", "-f", help="file index (1-based) or part of the file name")
    p.add_argument("--no-start", action="store_true", help="upload only, do not start")
    p.add_argument("--slice-only", action="store_true", help="do not send to the printer")
    p.add_argument("--no-leveling", action="store_true", help="skip bed leveling (Centauri Carbon stock firmware)")
    p.add_argument("--copies", type=int, help="copies on the plate (as many as fit)")
    p.add_argument("--rotate-x", type=float, help="tilt about X in degrees before slicing")
    p.add_argument("--rotate-y", type=float, help="tilt about Y in degrees before slicing")
    p.add_argument("--scale", type=int, help="size in percent")
    p.add_argument("--orient", action=argparse.BooleanOptionalAction, default=None,
                   help="lay flat automatically (default: printer setting)")

    f = sub.add_parser("files", help="list the files of a model")
    f.add_argument("link")

    s = sub.add_parser("status", help="show printer status")
    s.add_argument("--printer", "-p")

    pr = sub.add_parser("presets", help="list OrcaSlicer presets")
    pr.add_argument("kind", choices=["machine", "process", "filament"])
    pr.add_argument("--search", "-s", default="")

    pa = sub.add_parser("pair", help="show a QR code that connects the PocketPrint3D app to this server")
    pa.add_argument("--url", required=True,
                    help="address the phone uses at home, e.g. http://192.168.1.10:8484")
    pa.add_argument("--remote-url", default="",
                    help="optional address away from home, e.g. http://100.64.1.2:8484 (Tailscale)")

    sub.add_parser("serve", help="run the web UI / API")
    sub.add_parser("printers", help="list configured printers")

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if a.cmd == "serve":
        # Unraid template / Home Assistant add-on: create or refresh config.yaml from the form
        from . import bootstrap
        cfg_path = a.config or os.environ.get("PRINTSHARE_CONFIG", "/config/config.yaml")
        os.environ["PRINTSHARE_CONFIG"] = cfg_path
        try:
            info = bootstrap.ensure_config(cfg_path)
        except ValueError as e:
            print(f"Error in the printer settings: {e}", file=sys.stderr)
            return 1
        print(bootstrap.banner(info, bootstrap.server_url(), bootstrap.remote_url()), flush=True)
    settings = load_settings(a.config)

    try:
        if a.cmd == "print":
            opts = JobOptions(copies=a.copies, rotate_x=a.rotate_x, rotate_y=a.rotate_y, scale=a.scale,
                              orient=a.orient)
            opts.check_plate()
            res = asyncio.run(run_job(settings, a.link, a.printer, a.file,
                                      send=not a.slice_only, start=not a.no_start,
                                      progress=lambda m: print(f"• {m}", flush=True),
                                      options=opts, leveling=False if a.no_leveling else None))
            print(json.dumps(res.as_dict(), indent=2))
        elif a.cmd == "files":
            files = Fetcher(settings.thingiverse_token).list_files(a.link)
            for i, fl in enumerate([x for x in files if x.sliceable], 1):
                print(f"{i:>2}: {fl.name}  {fl.size or ''}")
            for fl in (x for x in files if not x.sliceable):
                print(f"  -: {fl.name}  (not sliceable)")
        elif a.cmd == "status":
            print(json.dumps(asyncio.run(get_adapter(settings.printer(a.printer)).status()),
                             indent=2, default=str))
        elif a.cmd == "presets":
            print("\n".join(Slicer(settings).library.names(a.kind, a.search)))
        elif a.cmd == "printers":
            for pc in settings.printers:
                print(f"{pc.id:<16} {pc.type:<12} {pc.host or pc.url}  [{pc.slicing.machine}]")
        elif a.cmd == "pair":
            print_pairing(a.url, settings.api_token, a.remote_url)
        elif a.cmd == "serve":
            import uvicorn
            uvicorn.run("printshare.api:app", host="0.0.0.0", port=8484)
    except (FetchError, KeyError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def pairing_link(url: str, token: str, remote: str = "") -> str:
    """QR content for the app; `remote` = second address for use away from home (e.g. Tailscale)."""
    from urllib.parse import urlencode
    q = {"url": url.rstrip("/"), "token": token}
    if remote:
        q["remote"] = remote.rstrip("/")
    return "printshare://connect?" + urlencode(q)


def print_pairing(url: str, token: str, remote: str = "") -> None:
    for u, flag in ((url, "--url"), (remote, "--remote-url")):
        if u and not u.startswith(("http://", "https://")):
            raise ValueError(f"{flag} must start with http:// or https://")
    import segno
    link = pairing_link(url, token, remote)
    print("Scan this code in the PocketPrint3D app (Settings → Connect server → Scan QR code):\n")
    segno.make(link, error="m").terminal(compact=True)
    print(f"\nOr enter manually:\n  Server: {url.rstrip('/')}")
    if remote:
        print(f"  Away from home: {remote.rstrip('/')}")
    print(f"  Token:  {token or '(none)'}")


if __name__ == "__main__":
    sys.exit(main())
