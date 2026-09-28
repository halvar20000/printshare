"""Link -> download -> slice -> send to printer.

The app uses two steps (`prepare_job`, then `send_job` after the user confirmed);
`run_job` does both at once for the CLI and the one-shot `/api/print` endpoint.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import JobOptions, Settings
from .fetch import Fetcher, choose_file
from .printers import get_adapter
from .slicer import Slicer

log = logging.getLogger("printshare")

_slice_slots: threading.BoundedSemaphore | None = None
_slots_lock = threading.Lock()


def _slots(settings: Settings) -> threading.BoundedSemaphore:
    global _slice_slots
    with _slots_lock:
        if _slice_slots is None:
            _slice_slots = threading.BoundedSemaphore(max(1, settings.max_parallel_slices))
        return _slice_slots


@dataclass
class JobResult:
    printer: str
    source_file: str
    gcode: str
    print_time: str | None
    filament_g: float | None
    filament_m: float | None
    layers: int | None = None
    profiles: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    sent: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slice_queued(settings: Settings, say: Callable[[str], None], *args: Any):
    slots = _slots(settings)
    if not slots.acquire(blocking=False):
        say("Waiting for another slice job to finish")
        slots.acquire()
    try:
        return Slicer(settings).slice(*args)
    finally:
        slots.release()


async def prepare_job(settings: Settings, link: str, printer_id: str | None = None,
                      file_choice: str | int | None = None, options: JobOptions | None = None,
                      out_name: str | None = None,
                      progress: Callable[[str], None] | None = None) -> JobResult:
    """Download and slice; nothing is sent to the printer."""
    say = progress or (lambda msg: log.info(msg))
    printer = settings.printer(printer_id)
    slicing = (options or JobOptions()).apply(printer.slicing)
    fetcher = Fetcher(settings.thingiverse_token)

    say("Looking up model files")
    files = await asyncio.to_thread(fetcher.list_files, link)
    chosen = choose_file(files, file_choice)

    dl_dir = Path(tempfile.mkdtemp(prefix="dl-", dir=settings.work_dir))
    try:
        say(f"Downloading {chosen.name}")
        model = await asyncio.to_thread(fetcher.download, chosen, dl_dir)

        say(f"Slicing for {printer.name or printer.id}")
        # own folder per job, so jobs for the same model don't overwrite each other's G-code
        out_dir = Path(settings.gcode_dir) / printer.id
        if out_name:
            out_dir = out_dir / out_name
        # blocking work runs in a thread so the web server stays responsive
        result = await asyncio.to_thread(_slice_queued, settings, say, model, printer, out_dir, slicing)
        say(f"Sliced: {result.print_time or '?'} / {result.filament_g or '?'} g")
        profiles = {"machine": slicing.machine_file or slicing.machine, "process": slicing.process,
                    "filament": slicing.filament, "bed_type": slicing.bed_type}
        overrides = (options or JobOptions()).process_overrides()
        return JobResult(printer.id, chosen.name, str(result.gcode_path), result.print_time,
                         result.filament_g, result.filament_m, result.layers, profiles, overrides)
    finally:
        shutil.rmtree(dl_dir, ignore_errors=True)


async def send_job(settings: Settings, result: JobResult, start: bool,
                   progress: Callable[[str], None] | None = None, leveling: bool | None = None) -> dict[str, Any]:
    say = progress or (lambda msg: log.info(msg))
    say("Sending to printer" + (" and starting" if start else ""))
    sent = await get_adapter(settings.printer(result.printer)).send(Path(result.gcode), start=start, leveling=leveling)
    result.sent = sent
    say("Done")
    return sent


async def run_job(settings: Settings, link: str, printer_id: str | None = None,
                  file_choice: str | int | None = None, send: bool = True, start: bool = True,
                  progress: Callable[[str], None] | None = None,
                  options: JobOptions | None = None, leveling: bool | None = None) -> JobResult:
    result = await prepare_job(settings, link, printer_id, file_choice, options, progress=progress)
    if send:
        await send_job(settings, result, start, progress, leveling=leveling)
    return result
