"""What became of a started print (0.33.0): a job stays "started" until the printer shows it finished or cancelled.

The same signals as the spool bookings (cloud/bookings.py): the printer's file name and state. Whoever sees the printer
reports it - the home server for its printers, the cloud for printers behind a bridge, the app for printers on its Wi-Fi.
  printing the job's file          → remember it was seen, and the progress
  finished                         → "finished"
  cancelled / error                → "cancelled"
  idle / another file afterwards   → "finished" when it got to ≥ 99 %, else "cancelled" (only once it was seen printing)
  never seen printing for 6 hours  → left as "started" (the printer may have been off; nothing is guessed)
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .cloud.bookings import same_file

TRACKED = ("started",)
STALE_DONE_S = 10 * 60


def printer_file(job: dict[str, Any]) -> str | None:
    """The job's file name on the printer."""
    if job.get("printer_file"):
        return str(job["printer_file"])
    gcode = (job.get("result") or {}).get("gcode")
    return Path(gcode).name if gcode else None


def track(job: dict[str, Any], status: dict[str, Any] | None, kind: str | None, now: float | None = None) -> bool:
    """Update a started job from the printer's status (`kind` = api.printer_kind of its state). True if it changed."""
    if job.get("state") not in TRACKED or not status:
        return False
    now = now or time.time()
    name = printer_file(job)
    if not name:
        return False
    if same_file(status.get("file"), name):
        if kind in ("active", "paused"):
            changed = not job.get("seen_printing") or job.get("progress") != status.get("progress")
            job["seen_printing"] = True
            if isinstance(status.get("progress"), (int, float)):
                job["progress"] = round(float(status["progress"]), 1)
            return changed
        if kind in ("done", "stopped", "error"):
            # right after the start the printer may still show the previous run of the same file as over
            if not job.get("seen_printing") and now - float(job.get("started_at") or 0) < STALE_DONE_S:
                return False
            return _end(job, "finished" if kind == "done" else "cancelled", now)
        if job.get("seen_printing"):              # idle with the file still shown (PrusaLink after FINISHED)
            return _end(job, "finished" if (job.get("progress") or 0) >= 99 else "cancelled", now)
        return False
    if job.get("seen_printing"):                   # the printer moved on: finished unseen, or replaced
        return _end(job, "finished" if (job.get("progress") or 0) >= 99 else "cancelled", now)
    return False


def _end(job: dict[str, Any], state: str, now: float) -> bool:
    job.update(state=state, finished_at=now)
    if state == "finished":
        job["progress"] = 100.0
    return True
