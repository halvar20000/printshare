"""Filament per slot (load / unload / set material and colour) - shared by the printer adapters that support it.

Materials with Bambu's generic filament ids (`tray_info_idx`, from OrcaSlicer 2.4.2's BBL profiles "Generic … @base")
and nozzle temperatures: the range the printer checks the slot against (PLA/PETG as a P1S reports its own generic
trays), and the temperature used to load/unload.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Material:
    name: str          # shown in the app
    type: str          # filament type the printer / slicer uses
    bambu_id: str      # tray_info_idx of the generic Bambu profile
    temp_min: int
    temp_max: int
    load_temp: int     # nozzle temperature for loading / unloading


MATERIALS: tuple[Material, ...] = (
    Material("PLA", "PLA", "GFL99", 190, 240, 220),
    Material("PLA Silk", "PLA", "GFL96", 190, 240, 220),
    Material("PLA-CF", "PLA-CF", "GFL98", 210, 240, 230),
    Material("PETG", "PETG", "GFG99", 220, 270, 250),
    Material("PETG-CF", "PETG-CF", "GFG98", 240, 270, 260),
    Material("ABS", "ABS", "GFB99", 240, 280, 260),
    Material("ASA", "ASA", "GFB98", 240, 280, 260),
    Material("TPU", "TPU", "GFU99", 200, 250, 230),
    Material("PA", "PA", "GFN99", 260, 290, 280),
    Material("PA-CF", "PA-CF", "GFN98", 260, 300, 280),
    Material("PC", "PC", "GFC99", 260, 290, 280),
    Material("PVA", "PVA", "GFS99", 190, 230, 220),
)
ACTIONS = ("load", "unload", "set")


def material(name: str | None) -> Material | None:
    """By name ("PETG"), or by type when only the type is known (a slot that says "PLA-CF")."""
    if not name:
        return None
    n = name.strip().upper()
    return next((m for m in MATERIALS if m.name.upper() == n), None) or next((m for m in MATERIALS if m.type == n), None)


def colour(value: str | None) -> str | None:
    """"#ff0000" / "FF0000" / "FF0000FF" → "FF0000" (None when it isn't a colour)."""
    v = (value or "").strip().lstrip("#")
    return v[:6].upper() if re.fullmatch(r"[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", v) else None


def materials_json() -> list[dict[str, Any]]:
    return [{"name": m.name, "type": m.type, "temp_min": m.temp_min, "temp_max": m.temp_max, "load_temp": m.load_temp}
            for m in MATERIALS]
