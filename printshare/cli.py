"""Command line: `printshare print <link> --printer cc-thomas` etc."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import load_settings
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

    f = sub.add_parser("files", help="list the files of a model")
    f.add_argument("link")

    s = sub.add_parser("status", help="show printer status")
    s.add_argument("--printer", "-p")

    pr = sub.add_parser("presets", help="list OrcaSlicer presets")
    pr.add_argument("kind", choices=["machine", "process", "filament"])
    pr.add_argument("--search", "-s", default="")

    sub.add_parser("serve", help="run the web UI / API")
    sub.add_parser("printers", help="list configured printers")

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = load_settings(a.config)

    try:
        if a.cmd == "print":
            res = asyncio.run(run_job(settings, a.link, a.printer, a.file,
                                      send=not a.slice_only, start=not a.no_start,
                                      progress=lambda m: print(f"• {m}", flush=True)))
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
        elif a.cmd == "serve":
            import uvicorn
            uvicorn.run("printshare.api:app", host="0.0.0.0", port=8484)
    except (FetchError, KeyError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
