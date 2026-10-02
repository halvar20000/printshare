"""Link -> download -> slice -> send to printer.

The app uses two steps (`prepare_job`, then `send_job` after the user confirmed);
`run_job` does both at once for the CLI and the one-shot `/api/print` endpoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import JobOptions, Settings
from . import lanes as lane_map
from . import model_info
from .fetch import Fetcher, RemoteFile, choose_file
from .printers import get_adapter
from .slicer import Slicer
from .manyfold import client_for as manyfold_client

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
    # multicolour: [{"index", "color", "preset", "grams"}] per filament of the model (empty = one colour)
    filaments: list[dict[str, Any]] = field(default_factory=list)
    # plate options: copies asked for and copies that fit (None when only one was asked for)
    copies_requested: int | None = None
    copies: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


CACHE_TTL_S = 24 * 3600


def _prune_cache(cache: Path) -> None:
    now = time.time()
    for d in cache.iterdir() if cache.is_dir() else []:
        try:
            if now - d.stat().st_mtime > CACHE_TTL_S:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def fetch_model(settings: Settings, link: str, file_choice: str | int | None = None,
                say: Callable[[str], None] | None = None) -> tuple[RemoteFile, Path]:
    """List + download a model file (blocking). Downloads are kept for a day, so looking at the
    colours of a model and slicing it later fetch the file only once."""
    say = say or (lambda msg: log.info(msg))
    fetcher = Fetcher(settings.thingiverse_token, manyfold=manyfold_client(settings))
    say("Looking up model files")
    chosen = choose_file(fetcher.list_files(link), file_choice)
    if chosen.source == "local":
        return chosen, Path(chosen.file_id)
    cache = Path(settings.work_dir) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    _prune_cache(cache)
    key = hashlib.sha1(f"{chosen.source}|{chosen.model_id}|{chosen.file_id}|{chosen.name}".encode()).hexdigest()[:20]
    target = cache / key
    hit = next((f for f in target.iterdir() if f.is_file()), None) if target.is_dir() else None
    if hit:
        os.utime(target)
        return chosen, hit
    say(f"Downloading {chosen.name}")
    tmp = Path(tempfile.mkdtemp(prefix="dl-", dir=cache))
    try:
        path = fetcher.download(chosen, tmp)
        try:
            tmp.rename(target)
        except OSError:           # another request downloaded it at the same time
            shutil.rmtree(tmp, ignore_errors=True)
        return chosen, next(f for f in target.iterdir() if f.is_file()) if target.is_dir() else path
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def inspect_model(settings: Settings, link: str, file_choice: str | int | None = None) -> dict[str, Any]:
    """Colours/filaments of a model before slicing (blocking)."""
    chosen, path = fetch_model(settings, link, file_choice)
    return {"file": chosen.name, **model_info.inspect(path)}


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
    chosen, model = await asyncio.to_thread(fetch_model, settings, link, file_choice, say)
    say(f"Slicing for {printer.name or printer.id}")
    # own folder per job, so jobs for the same model don't overwrite each other's G-code
    out_dir = Path(settings.gcode_dir) / printer.id
    if out_name:
        out_dir = out_dir / out_name
    # blocking work runs in a thread so the web server stays responsive
    result = await asyncio.to_thread(_slice_queued, settings, say, model, printer, out_dir, slicing)
    say(f"Sliced: {result.print_time or '?'} / {result.filament_g or '?'} g")
    if slicing.copies > 1 and result.copies is not None and result.copies < slicing.copies:
        say(f"Only {result.copies} of {slicing.copies} copies fit on the plate")
    profiles = {"machine": slicing.machine_file or slicing.machine, "process": slicing.process,
                "filament": slicing.filament, "bed_type": slicing.bed_type}
    overrides = (options or JobOptions()).process_overrides()
    return JobResult(printer.id, chosen.name, str(result.gcode_path), result.print_time,
                     result.filament_g, result.filament_m, result.layers, profiles, overrides,
                     filaments=result.filaments,
                     copies_requested=slicing.copies if slicing.copies > 1 else None, copies=result.copies)


async def send_job(settings: Settings, result: JobResult, start: bool,
                   progress: Callable[[str], None] | None = None, leveling: bool | None = None,
                   tools: dict[int, int] | None = None, spool_id: int | None = None) -> dict[str, Any]:
    """tools: OrcaSlicer tool -> printer tool (lane selection, issue #6); the G-code is rewritten on a copy.
    spool_id: Spoolman spool that Moonraker books this print on (printers with Moonraker's [spoolman])."""
    say = progress or (lambda msg: log.info(msg))
    say("Sending to printer" + (" and starting" if start else ""))
    gcode = Path(result.gcode)
    tmp = None
    if tools and any(k != v for k, v in tools.items()):
        tmp = Path(tempfile.mkdtemp(prefix="lanes-", dir=settings.work_dir))
        gcode = await asyncio.to_thread(lane_map.remap_tools, gcode, tools, tmp)
    adapter = get_adapter(settings.printer(result.printer))
    if spool_id is not None:
        if not hasattr(adapter, "set_spool"):
            raise ValueError("this printer can't track a Spoolman spool itself")
        await adapter.set_spool(spool_id)
    try:
        sent = await adapter.send(gcode, start=start, leveling=leveling)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    if tools:
        sent = {**sent, "tools": {str(k): v for k, v in tools.items()}}
    if spool_id is not None:
        sent = {**sent, "spool_id": spool_id}
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
