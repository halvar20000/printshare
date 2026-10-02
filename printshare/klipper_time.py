"""Exact print times for Klipper printers with klipper_estimator (https://github.com/Annex-Engineering/klipper_estimator,
MIT): it replays the G-code with Klipper's motion planning and the printer's own limits (Moonraker:
/printer/objects/query?configfile=settings) and rewrites the time estimate + M73 progress lines of the file.
OrcaSlicer is often 10-20 % off for Klipper machines.

Only for Moonraker printers this server can reach (own servers; cloud printers have no address). The printer's limits
are kept in <config dir>/klipper_estimator/<printer>.json, so it also works while the printer is switched off. Any
failure leaves the G-code as OrcaSlicer wrote it.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import PrinterConfig

log = logging.getLogger(__name__)
DEFAULT_BIN = "/opt/klipper_estimator/klipper_estimator"
TIMEOUT_S = 300


def binary() -> str | None:
    path = os.environ.get("KLIPPER_ESTIMATOR") or (DEFAULT_BIN if Path(DEFAULT_BIN).is_file() else None) \
        or shutil.which("klipper_estimator")
    return path if path and os.access(path, os.X_OK) else None


def _candidates(printer: PrinterConfig) -> list[str]:
    from .printers.moonraker import Moonraker
    try:
        return Moonraker(printer).candidates           # the configured URL, then :7125 (as for printing)
    except ValueError:
        return []


def post_process(gcode: Path, printer: PrinterConfig, cache_dir: str | Path) -> bool:
    """Correct the print time in `gcode` (in place). True when klipper_estimator processed the file."""
    exe = binary()
    if exe is None or printer.type != "moonraker" or not printer.url:
        return False
    cache = Path(cache_dir) / "klipper_estimator" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', printer.id)}.json"
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    for url in _candidates(printer):
        cmd = [exe, "--config_moonraker_url", url, "--config_moonraker_cache_file", str(cache),
               "--config_moonraker_ignore_error"]
        if printer.api_key:
            cmd += ["--config_moonraker_api_key", printer.api_key]
        try:
            proc = subprocess.run([*cmd, "post-process", str(gcode)], capture_output=True, text=True, timeout=TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("klipper_estimator failed for %s: %s", printer.id, e)
            return False
        if proc.returncode == 0:
            return True
        if cache.is_file():
            break                          # the saved limits were used and it still failed: don't try more URLs
    log.info("klipper_estimator skipped for %s (printer not reachable, no saved limits yet)", printer.id)
    return False
