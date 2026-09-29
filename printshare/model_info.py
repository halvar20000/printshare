"""What is in a model file before slicing: filaments (colours) of a 3MF project (spec MA-04).

Supports the project 3MFs that Printables/MakerWorld models usually come as:
* OrcaSlicer / Bambu Studio: Metadata/project_settings.config (JSON) + Metadata/model_settings.config
* PrusaSlicer: Metadata/Slic3r_PE.config (";" key = value lines) + Metadata/Slic3r_PE_model.config
Painted colours (MMU painting) are detected but not decoded: then all project filaments count as used.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?$")
MAX_FILAMENTS = 16


def _color(value: Any) -> str:
    m = _HEX.match(str(value or "").strip())
    return f"#{m.group(1).upper()}" if m else "#808080"


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None or value == "":
        return []
    return [v.strip().strip('"') for v in str(value).split(";")]


def _extruders_from_xml(data: bytes) -> set[int]:
    """Object/part/volume 'extruder' metadata (Orca/Bambu model_settings, Prusa Slic3r_PE_model)."""
    used: set[int] = set()
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return used
    for md in root.iter("metadata"):
        if md.get("key") == "extruder":
            try:
                n = int(md.get("value", "0"))
            except ValueError:
                continue
            if n > 0:
                used.add(n)
    return used


def _painted(z: zipfile.ZipFile) -> bool:
    for name in z.namelist():
        if name.startswith("3D/") and name.endswith(".model"):
            with z.open(name) as fh:
                while chunk := fh.read(1 << 20):
                    if b"paint_color=" in chunk or b"mmu_segmentation=" in chunk:
                        return True
    return False


def inspect(path: Path) -> dict[str, Any]:
    """{"filaments": [{"index", "color", "type", "name"}], "used": [indices], "painted", "source"}.

    A single-colour model (STL/OBJ/STEP or a 3MF without colour data) returns one filament or none.
    """
    empty: dict[str, Any] = {"filaments": [], "used": [], "painted": False, "source": None}
    if path.suffix.lower() != ".3mf":
        return empty
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return empty
    with z:
        names = set(z.namelist())
        colours: list[str] = []
        types: list[str] = []
        presets: list[str] = []
        used: set[int] = set()
        source = None
        if "Metadata/project_settings.config" in names:           # OrcaSlicer / Bambu Studio
            try:
                cfg = json.loads(z.read("Metadata/project_settings.config"))
            except (ValueError, UnicodeDecodeError):
                cfg = {}
            colours = _as_list(cfg.get("filament_colour"))
            types = _as_list(cfg.get("filament_type"))
            presets = _as_list(cfg.get("filament_settings_id"))
            source = "orca"
            if "Metadata/model_settings.config" in names:
                used = _extruders_from_xml(z.read("Metadata/model_settings.config"))
        elif "Metadata/Slic3r_PE.config" in names:                 # PrusaSlicer
            text = z.read("Metadata/Slic3r_PE.config").decode("utf-8", "replace")
            kv = dict(re.findall(r"^;\s*([\w]+)\s*=\s*(.*)$", text, re.M))
            colours = _as_list(kv.get("extruder_colour")) if any(
                c.strip("#") for c in _as_list(kv.get("extruder_colour"))) else []
            colours = colours or _as_list(kv.get("filament_colour"))
            types = _as_list(kv.get("filament_type"))
            presets = _as_list(kv.get("filament_settings_id"))
            source = "prusa"
            if "Metadata/Slic3r_PE_model.config" in names:
                used = _extruders_from_xml(z.read("Metadata/Slic3r_PE_model.config"))
        else:
            return empty
        painted = _painted(z)

    count = min(len(colours), MAX_FILAMENTS)
    filaments = [{"index": i + 1, "color": _color(colours[i]),
                  "type": (types[i] if i < len(types) else "").strip('"') or None,
                  "name": (presets[i] if i < len(presets) else "").strip('"') or None}
                 for i in range(count)]
    if painted or not used:
        # painted parts can use any filament; without assignments everything prints with filament 1
        used_list = list(range(1, count + 1)) if painted else ([1] if count else [])
    else:
        used_list = sorted(u for u in used if u <= count) or [1]
    return {"filaments": filaments, "used": used_list, "painted": painted, "source": source}
