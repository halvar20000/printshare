"""What a G-code from the OrcaSlicer desktop says about itself (docs/WEB.md step 3, "send from OrcaSlicer").

Orca writes its settings at the end (`; CONFIG_BLOCK_START`): `; printer_settings_id = Elegoo Centauri Carbon 0.4 nozzle`,
`; print_settings_id = …`, `; filament_settings_id = "Elegoo PLA @ECC";"…"` (one per filament), `; filament_colour =
#F2754E;#FFFFFF`, `; filament_type = PLA;PETG`. Checked on a real Orca 2.4.2 G-code.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_LINE = re.compile(r"^; (printer_settings_id|print_settings_id|filament_settings_id|filament_colour|filament_type|printer_model)"
                   r" = (.*)$", re.M)


def _split(value: str) -> list[str]:
    return [v.strip().strip('"').strip() for v in value.split(";")] if value.strip() else []


def orca_settings(gcode: Path, tail_bytes: int = 600_000) -> dict[str, Any]:
    """{"printer", "printer_model", "process", "filaments": [...], "colours": [...], "types": [...]} - empty if not an
    Orca/Bambu/PrusaSlicer-style G-code."""
    with gcode.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - tail_bytes))
        text = fh.read().decode("utf-8", "ignore")
    found: dict[str, str] = {}
    for key, value in _LINE.findall(text):
        found[key] = value.strip()
    out: dict[str, Any] = {}
    if found.get("printer_settings_id"):
        out["printer"] = found["printer_settings_id"].strip('"')
    if found.get("printer_model"):
        out["printer_model"] = found["printer_model"].strip('"')
    if found.get("print_settings_id"):
        out["process"] = found["print_settings_id"].strip('"')
    out["filaments"] = _split(found.get("filament_settings_id", ""))
    out["colours"] = [c if re.fullmatch(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", c) else None
                      for c in _split(found.get("filament_colour", ""))]
    out["types"] = _split(found.get("filament_type", ""))
    return out
