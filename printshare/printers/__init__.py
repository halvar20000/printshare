"""Printer adapters. Each adapter uploads G-code, optionally starts it, reports status and
pauses/resumes/cancels the current print."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ..camera import Camera
from ..config import PrinterConfig


class PrinterAdapter(Protocol):
    # leveling: bed leveling before this print (None = printer default); see LEVELING_TYPES
    async def send(self, gcode: Path, start: bool = True, leveling: bool | None = None) -> dict[str, Any]: ...
    async def status(self) -> dict[str, Any]: ...
    async def control(self, action: str) -> None: ...  # "pause" | "resume" | "cancel"
    async def camera(self) -> "Camera | None": ...      # where the camera image comes from (issue #3)
    # Printer control (issue #5). controls() says what the printer has, so the app only shows that:
    #   {"heaters": [{"id": "nozzle", "max": 300}, …], "fans": [{"id": "part"}, …],
    #    "lights": [{"id": "light"}], "speed": {"modes": [50, 100, 130, 160]} | {"min": 10, "max": 300},
    #    "history": bool}
    # status() then also reports "heaters" {id: {"actual", "target"}}, "fans" {id: %}, "lights" {id: bool},
    # "speed" (%). adjust(kind, id, value) with kind "heater" | "fan" | "light" | "speed".
    async def controls(self) -> dict[str, Any]: ...
    async def adjust(self, kind: str, target: str, value: Any) -> None: ...


CONTROL_ACTIONS = ("pause", "resume", "cancel")
PRINTER_TYPES = ("elegoo_sdcp", "moonraker", "prusalink", "octoprint", "bambu_lan")
# printer types that need an explicit OrcaSlicer printer model (never the Centauri default)
NEEDS_MACHINE = ("prusalink", "octoprint", "bambu_lan")
# printer types that can switch bed leveling per print (DO-01). Klipper/Prusa/OctoPrint do it in their
# start G-code; COSMOS' PRINT_START parameter for it is still an open question.
LEVELING_TYPES = ("elegoo_sdcp",)


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
    if cfg.type == "bambu_lan":
        from .bambu import Bambu
        return Bambu(cfg)
    raise ValueError(f"Unknown printer type {cfg.type!r} (use {', '.join(PRINTER_TYPES)})")
