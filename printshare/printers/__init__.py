"""Printer adapters. Each adapter uploads G-code, optionally starts it, and reports status."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ..config import PrinterConfig


class PrinterAdapter(Protocol):
    async def send(self, gcode: Path, start: bool = True) -> dict[str, Any]: ...
    async def status(self) -> dict[str, Any]: ...


def get_adapter(cfg: PrinterConfig) -> PrinterAdapter:
    if cfg.type == "elegoo_sdcp":
        from .elegoo import ElegooSDCP
        return ElegooSDCP(cfg)
    if cfg.type == "moonraker":
        from .moonraker import Moonraker
        return Moonraker(cfg)
    raise ValueError(f"Unknown printer type {cfg.type!r} (use elegoo_sdcp or moonraker)")
