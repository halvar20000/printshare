"""Layer data for the G-code preview in the app (spec SL-06/SL-07, BE-03).

Parses the sliced G-code into extrusion polylines per layer and line type (OrcaSlicer's `;TYPE:`
comments) and returns a compact JSON structure: coordinates as integers in 1/20 mm, collinear and
very short segments merged. Travel moves and retractions are left out.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

UNIT = 20                     # coordinates in 1/20 mm
COLLINEAR_MM = 0.02           # mm - drop points this close to the straight line through their neighbours
ARC_STEP = math.radians(12)   # G2/G3 are drawn as polylines with this angular step
_WORD = re.compile(r"([A-Z])([-+]?\d*\.?\d+)")


class _Layer:
    def __init__(self, z: float):
        self.z = z
        self.paths: list[list[int]] = []   # [type_index, x0, y0, x1, y1, ...]


def _simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = [pts[0]]
    for i in range(1, len(pts)):
        p = pts[i]
        if p == out[-1]:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            # b lies on the line a->p: replace b by p
            ab, ap = (b[0] - a[0], b[1] - a[1]), (p[0] - a[0], p[1] - a[1])
            lap = math.hypot(*ap)
            if lap > 0 and abs(ab[0] * ap[1] - ab[1] * ap[0]) / lap < COLLINEAR_MM and ab[0] * ap[0] + ab[1] * ap[1] > 0:
                out[-1] = p
                continue
        out.append(p)
    return out


def parse(lines) -> dict[str, Any]:
    types: list[str] = []
    type_index: dict[str, int] = {}
    layers: list[_Layer] = []
    by_z: dict[float, _Layer] = {}
    markers = False                      # file has ;LAYER_CHANGE markers (Orca, PrusaSlicer, Bambu)
    layer: _Layer | None = None
    x = y = z = e = 0.0
    abs_xyz, abs_e = True, True
    cur_type = "Custom"
    poly: list[tuple[float, float]] | None = None
    poly_type = -1
    poly_layer: _Layer | None = None
    # the model's extent, without start/end code (e.g. the purge line at the edge of the plate)
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    all_bounds = [math.inf, math.inf, -math.inf, -math.inf]

    def flush() -> None:
        nonlocal poly
        if poly and len(poly) >= 2 and poly_layer is not None:
            flat = [poly_type]
            for px, py in _simplify(poly):
                flat += [round(px * UNIT), round(py * UNIT)]
            poly_layer.paths.append(flat)
        poly = None

    def tidx(name: str) -> int:
        if name not in type_index:
            type_index[name] = len(types)
            types.append(name)
        return type_index[name]

    def layer_for(zz: float) -> _Layer:
        nonlocal layer
        if markers and layer is not None:
            return layer
        key = round(zz, 3)
        if key not in by_z:
            by_z[key] = _Layer(key)
            layers.append(by_z[key])
        layer = by_z[key]
        return layer

    def extrude_to(px: float, py: float) -> None:
        nonlocal poly, poly_type, poly_layer
        lay = layer_for(z)
        t = tidx(cur_type)
        if poly is None or poly_type != t or poly_layer is not lay or poly[-1] != (x, y):
            flush()
            poly, poly_type, poly_layer = [(x, y)], t, lay
        poly.append((px, py))
        for b in ((all_bounds,) if cur_type == "Custom" else (all_bounds, bounds)):
            b[0], b[1] = min(b[0], x, px), min(b[1], y, py)
            b[2], b[3] = max(b[2], x, px), max(b[3], y, py)

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line[0] == ";":
            c = line[1:].strip()
            if c.startswith("TYPE:"):
                cur_type = c[5:].strip() or "Custom"
            elif c == "LAYER_CHANGE":
                flush()
                if not markers and layers:
                    layer = layers[-1]    # the prime line from the start G-code belongs to layer 1
                else:
                    layer = _Layer(z)
                    layers.append(layer)
                markers = True
            elif c.startswith("Z:") and markers and layer is not None:   # height of the layer just started
                try:
                    layer.z = float(c[2:])
                except ValueError:
                    pass
            continue
        code = line.split(";", 1)[0].upper()
        if not code:
            continue
        cmd, _, rest = code.partition(" ")
        if cmd in ("G0", "G1", "G2", "G3"):
            w = {k: float(v) for k, v in _WORD.findall(rest)}
            nx = (w["X"] if abs_xyz else x + w["X"]) if "X" in w else x
            ny = (w["Y"] if abs_xyz else y + w["Y"]) if "Y" in w else y
            nz = (w["Z"] if abs_xyz else z + w["Z"]) if "Z" in w else z
            de = 0.0
            if "E" in w:
                de = w["E"] - e if abs_e else w["E"]
                e = w["E"] if abs_e else e + w["E"]
            z = nz
            moves = (nx, ny) != (x, y)
            if de > 1e-6 and moves:
                if cmd in ("G2", "G3") and ("I" in w or "J" in w):
                    cx, cy = x + w.get("I", 0.0), y + w.get("J", 0.0)
                    r = math.hypot(x - cx, y - cy)
                    a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
                    sweep = a1 - a0
                    if cmd == "G2" and sweep >= 0:
                        sweep -= 2 * math.pi
                    elif cmd == "G3" and sweep <= 0:
                        sweep += 2 * math.pi
                    steps = max(1, int(abs(sweep) / ARC_STEP))
                    for i in range(1, steps):
                        a = a0 + sweep * i / steps
                        px, py = cx + r * math.cos(a), cy + r * math.sin(a)
                        extrude_to(px, py)
                        x, y = px, py
                extrude_to(nx, ny)
            elif moves:
                flush()           # travel
            x, y = nx, ny
        elif cmd == "G90":
            abs_xyz = True
        elif cmd == "G91":
            abs_xyz = False
        elif cmd == "M82":
            abs_e = True
        elif cmd == "M83":
            abs_e = False
        elif cmd == "G92":
            w = {k: float(v) for k, v in _WORD.findall(rest)}
            x, y, z, e = w.get("X", x), w.get("Y", y), w.get("Z", z), w.get("E", e)
    flush()

    kept = [lay for lay in layers if lay.paths]
    return {
        "version": 1, "unit": UNIT, "types": types,
        "bounds": [round(b, 2) for b in (bounds if math.isfinite(bounds[0]) else all_bounds)] if kept else None,
        "layers": [{"z": round(lay.z, 3), "paths": lay.paths} for lay in kept],
    }


def build(gcode: Path, bed: tuple[float, float] | None = None) -> dict[str, Any]:
    """Preview for a G-code file; cached next to it (sliced G-code never changes)."""
    cache = gcode.with_suffix(".preview.json")
    if cache.is_file() and cache.stat().st_mtime >= gcode.stat().st_mtime:
        data = json.loads(cache.read_text())
    else:
        with gcode.open(encoding="utf-8", errors="replace") as fh:
            data = parse(fh)
        cache.write_text(json.dumps(data, separators=(",", ":")))
    data["bed"] = list(bed) if bed else None
    return data


def bed_size(printable_area: Any) -> tuple[float, float] | None:
    """Orca `printable_area` ["0x0", "256x0", "256x256", "0x256"] -> (256, 256)."""
    try:
        pts = [tuple(float(v) for v in str(p).split("x")) for p in printable_area]
        return (max(p[0] for p in pts) - min(p[0] for p in pts), max(p[1] for p in pts) - min(p[1] for p in pts))
    except (TypeError, ValueError, IndexError):
        return None
