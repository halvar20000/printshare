"""What became of a started print (0.33.0): a job stays "started" until the printer shows it finished or cancelled.

The same signals as the spool bookings (cloud/bookings.py): the printer's file name and state. Whoever sees the printer
reports it - the home server for its printers, the cloud for printers behind a bridge, the app for printers on its Wi-Fi.
  printing the job's file          → remember it was seen, and the progress
  finished                         → "finished"
  cancelled / error                → "cancelled"
  idle / another file afterwards   → "finished" when it got to ≥ 99 %, else "cancelled" (only once it was seen printing)
  never seen printing for 6 hours  → left as "started" (the printer may have been off; nothing is guessed)

Prints started elsewhere (0.40.0: OrcaSlicer straight to the printer, the printer's screen, Mainsail …) become jobs of
their own, kind "external", as soon as a printer is seen printing a file no job of the account stands for; from then on
they are followed by the same rules.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .cloud.bookings import same_file

TRACKED = ("started",)
STALE_DONE_S = 10 * 60
SENDING = ("sending", "uploading")   # a send of our own is under way: what the printer starts now is ours
OWN_START_S = 20 * 60                # a start of our own not seen printing yet may carry another name on the printer
EXTERNAL = "external"


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


def external(jobs: list[dict[str, Any]], printer_id: str, status: dict[str, Any] | None, kind: str | None,
             now: float | None = None) -> dict[str, Any] | None:
    """A print on this printer that none of these jobs (the account's jobs of this printer, already tracked with this
    status) stands for: the fields of a new "external" job, else None."""
    if not status or kind not in ("active", "paused"):
        return None
    name = status.get("file")
    if not isinstance(name, str) or not name.strip() or Path(name).name.startswith("pp3d-filament-"):
        return None       # empty, or the Centauri's load/unload file (motion.FILE_PREFIX)
    now = now or time.time()
    for job in jobs:
        state = job.get("state")
        if state in SENDING:
            return None
        if state in TRACKED and (same_file(name, printer_file(job) or "")
                                 or (not job.get("seen_printing")
                                     and now - float(job.get("started_at") or 0) < OWN_START_S)):
            return None
    progress = status.get("progress")
    return {"kind": EXTERNAL, "state": "started", "printer": printer_id, "printer_file": Path(name).name,
            "started_at": now, "seen_printing": True,
            "progress": round(float(progress), 1) if isinstance(progress, (int, float)) else None,
            "request": {"link": None, "printer": printer_id, "source": "printer"}}
