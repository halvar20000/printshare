"""Printer adapters. Each adapter uploads G-code, optionally starts it, reports status and
pauses/resumes/cancels the current print."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ..config import PrinterConfig


class PrinterAdapter(Protocol):
    async def send(self, gcode: Path, start: bool = True) -> dict[str, Any]: ...
    async def status(self) -> dict[str, Any]: ...
    async def control(self, action: str) -> None: ...  # "pause" | "resume" | "cancel"


CONTROL_ACTIONS = ("pause", "resume", "cancel")
PRINTER_TYPES = ("elegoo_sdcp", "moonraker", "prusalink", "octoprint")


def get_adapter(cfg: PrinterConfig) -> PrinterAdapter:
    if cfg.type == "elegoo_sdcp":
        from .elegoo import ElegooSDCP
        return ElegooSDCP(cfg)
    if cfg.type == "moonraker":
        from .moonraker import Moonraker
        return Moonraker(cfg)
    if cfg.type == "prusalink":
        from .prusalink import PrusaLink
        return PrusaLink(cfg)
    if cfg.type == "octoprint":
        from .octoprint import OctoPrint
        return OctoPrint(cfg)
    raise ValueError(f"Unknown printer type {cfg.type!r} (use {', '.join(PRINTER_TYPES)})")
