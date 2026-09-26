"""Link -> download -> slice -> send to printer."""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .fetch import Fetcher, choose_file
from .printers import get_adapter
from .slicer import Slicer

log = logging.getLogger("printshare")


@dataclass
class JobResult:
    printer: str
    source_file: str
    gcode: str
    print_time: str | None
    filament_g: float | None
    filament_m: float | None
    sent: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def run_job(settings: Settings, link: str, printer_id: str | None = None,
                  file_choice: str | int | None = None, send: bool = True, start: bool = True,
                  progress: Callable[[str], None] | None = None) -> JobResult:
    say = progress or (lambda msg: log.info(msg))
    printer = settings.printer(printer_id)
    fetcher = Fetcher(settings.thingiverse_token)

    say("Looking up model files")
    files = await asyncio.to_thread(fetcher.list_files, link)
    chosen = choose_file(files, file_choice)

    dl_dir = Path(tempfile.mkdtemp(prefix="dl-", dir=settings.work_dir))
    try:
        say(f"Downloading {chosen.name}")
        model = await asyncio.to_thread(fetcher.download, chosen, dl_dir)

        say(f"Slicing for {printer.name or printer.id}")
        # blocking work runs in a thread so the web server stays responsive
        result = await asyncio.to_thread(Slicer(settings).slice, model, printer,
                                         Path(settings.gcode_dir) / printer.id)
        say(f"Sliced: {result.print_time or '?'} / {result.filament_g or '?'} g")

        sent: dict[str, Any] = {}
        if send:
            say("Sending to printer" + (" and starting" if start else ""))
            sent = await get_adapter(printer).send(result.gcode_path, start=start)
            say("Done")
        return JobResult(printer.id, chosen.name, str(result.gcode_path),
                         result.print_time, result.filament_g, result.filament_m, sent)
    finally:
        shutil.rmtree(dl_dir, ignore_errors=True)
