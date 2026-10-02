"""Preview images in the G-code for the printer's screen (file list, print screen).

The OrcaSlicer CLI writes no thumbnails without a display (finding 5 in CLAUDE.md), so they are made here after slicing:
an isometric view of the sliced toolpaths (from gcode_preview, so copies, placement and colours are what gets printed),
drawn with Pillow - no GPU. Sizes and formats come from the printer preset (`thumbnails`, e.g. "16x16/QOI, 640x480/PNG";
`thumbnails_format` as the default), the blocks are the ones PrusaSlicer/OrcaSlicer write and printers read:
  ; thumbnail[_QOI|_JPG] begin WxH <base64 length>  /  ; <base64, 78 per line>  /  ; thumbnail[_QOI|_JPG] end
inside "; THUMBNAIL_BLOCK_START/END" right after the header block.
"""
from __future__ import annotations

import base64
import io
import logging
import math
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from . import gcode_preview

log = logging.getLogger(__name__)

# line types worth drawing: they make the outline and the surfaces (infill would only cost time)
DRAWN = ("Outer wall", "Overhang wall", "Top surface", "Bottom surface", "Support", "Support interface", "Brim", "Skirt")
DEFAULT_SPECS = [(32, 32, "PNG"), (300, 300, "PNG")]     # Klipper/Mainsail/Fluidd and OctoPrint show these
MAX_SPECS = 8


def specs(machine: dict[str, Any], default_when_missing: bool = True) -> list[tuple[int, int, str]]:
    """[(w, h, format)] from the printer preset."""
    raw = machine.get("thumbnails")
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    fallback = str(machine.get("thumbnails_format") or "PNG").upper()
    out = []
    for it in items:
        m = re.fullmatch(r"\s*(\d+)x(\d+)(?:/(\w+))?\s*", str(it))
        if m:
            w, h, fmt = int(m[1]), int(m[2]), (m[3] or fallback).upper()
            if 0 < w <= 1024 and 0 < h <= 1024 and fmt in ("PNG", "JPG", "QOI"):
                out.append((w, h, fmt))
    if not out and default_when_missing:
        out = list(DEFAULT_SPECS)
    return out[:MAX_SPECS]


# ---------------------------------------------------------------- drawing
def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return 0xF2, 0x75, 0x4E


def render(preview: dict[str, Any], size: int = 600) -> Image.Image | None:
    """Isometric picture (transparent background) of the toolpaths, longest side about `size` px."""
    unit = preview["unit"]
    types = preview["types"]
    drawn = {i for i, t in enumerate(types) if t in DRAWN}
    colors = [_rgb(c) for c in preview.get("filament_colors") or []] or [(0xF2, 0x75, 0x4E)]
    off = 2 if preview.get("version", 1) >= 2 else 1
    c45, s45 = math.cos(math.radians(45)), math.sin(math.radians(45))
    el = math.radians(30)
    ce, se = math.cos(el), math.sin(el)

    def proj(x: float, y: float, z: float) -> tuple[float, float, float]:
        rx, ry = (x - y) * c45, (x + y) * s45             # turned 45° about Z, seen from the front-left corner
        return rx, z * ce - ry * se, ry                    # screen x, screen y (up), depth (larger = nearer)

    segs = []              # (layer, depth, (x0, y0), (x1, y1), colour)
    # light from the viewer's left (+x side, a bit to the front): walls facing it are bright, the others shaded
    lx, ly = math.cos(math.radians(20)), math.sin(math.radians(20))
    for li, lay in enumerate(preview["layers"]):
        z = lay["z"]
        for p in lay["paths"]:
            if p[0] not in drawn:
                continue
            base = colors[(p[1] if off == 2 else 0) % len(colors)]
            top = types[p[0]] == "Top surface"
            ridge = 0.93 if li % 2 else 1.0                   # every other layer a touch darker: visible layer lines
            for i in range(off, len(p) - 3, 2):
                x0, y0, x1, y1 = p[i] / unit, p[i + 1] / unit, p[i + 2] / unit, p[i + 3] / unit
                dx, dy = x1 - x0, y1 - y0
                n = math.hypot(dx, dy) or 1.0
                # outward normal of a counter-clockwise outer wall = right-hand normal (dy, -dx)
                facing = (dy / n) * lx - (dx / n) * ly
                shade = 1.08 if top else (0.42 + 0.6 * max(0.0, facing) + 0.12 * max(0.0, -facing)) * ridge
                a, b = proj(x0, y0, z), proj(x1, y1, z)
                segs.append((li, (a[2] + b[2]) / 2, (a[0], a[1]), (b[0], b[1]),
                             tuple(min(255, int(ch * shade)) for ch in base)))
    if not segs:
        return None
    xs = [v for s in segs for v in (s[2][0], s[3][0])]
    ys = [v for s in segs for v in (s[2][1], s[3][1])]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    span = max(x1 - x0, y1 - y0, 1e-3)
    scale = (size - 8) / span
    w, h = int((x1 - x0) * scale) + 8, int((y1 - y0) * scale) + 8
    img = Image.new("RGBA", (max(w, 8), max(h, 8)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    width = max(1, round(0.45 * scale))
    segs.sort(key=lambda s: (s[0], s[1]))                 # bottom layers first, far (small depth) before near
    for _, _, a, b, col in segs:
        draw.line([((a[0] - x0) * scale + 4, (y1 - a[1]) * scale + 4), ((b[0] - x0) * scale + 4, (y1 - b[1]) * scale + 4)],
                  fill=col + (255,), width=width)
    return img


def fit(img: Image.Image, w: int, h: int) -> Image.Image:
    """The picture centred in w×h with transparent margins."""
    pic = img.copy()
    pic.thumbnail((max(1, w - max(2, w // 16)), max(1, h - max(2, h // 16))), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(pic, ((w - pic.width) // 2, (h - pic.height) // 2), pic)
    return out


# ---------------------------------------------------------------- encoding
def qoi(img: Image.Image) -> bytes:
    """QOI encoder (https://qoiformat.org/qoi-specification.pdf) - Pillow only reads QOI; Prusa printers want it."""
    img = img.convert("RGBA")
    w, h = img.size
    out = bytearray(b"qoif" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([4, 0]))
    index = [(0, 0, 0, 0)] * 64
    prev = (0, 0, 0, 255)
    run = 0
    raw = img.tobytes()                                   # RGBA, 4 bytes per pixel (getdata() is deprecated)
    px = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
    for i, cur in enumerate(px):
        if cur == prev:
            run += 1
            if run == 62 or i == len(px) - 1:
                out.append(0xC0 | (run - 1))
                run = 0
            continue
        if run:
            out.append(0xC0 | (run - 1))
            run = 0
        r, g, b, a = cur
        pos = (r * 3 + g * 5 + b * 7 + a * 11) % 64
        if index[pos] == cur:
            out.append(pos)
        else:
            index[pos] = cur
            if a == prev[3]:
                dr, dg, db = (r - prev[0] + 128) % 256 - 128, (g - prev[1] + 128) % 256 - 128, (b - prev[2] + 128) % 256 - 128
                dr_dg, db_dg = dr - dg, db - dg
                if -2 <= dr <= 1 and -2 <= dg <= 1 and -2 <= db <= 1:
                    out.append(0x40 | (dr + 2) << 4 | (dg + 2) << 2 | (db + 2))
                elif -32 <= dg <= 31 and -8 <= dr_dg <= 7 and -8 <= db_dg <= 7:
                    out += bytes([0x80 | (dg + 32), (dr_dg + 8) << 4 | (db_dg + 8)])
                else:
                    out += bytes([0xFE, r, g, b])
            else:
                out += bytes([0xFF, r, g, b, a])
        prev = cur
    return bytes(out + b"\x00" * 7 + b"\x01")


def encode(img: Image.Image, fmt: str) -> bytes:
    if fmt == "QOI":
        return qoi(img)
    buf = io.BytesIO()
    if fmt == "JPG":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        bg.save(buf, "JPEG", quality=85)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def blocks(img: Image.Image, wanted: list[tuple[int, int, str]]) -> str:
    out = ["; THUMBNAIL_BLOCK_START"]
    for w, h, fmt in wanted:
        b64 = base64.b64encode(encode(fit(img, w, h), fmt)).decode()
        tag = "thumbnail" if fmt == "PNG" else f"thumbnail_{fmt}"
        out.append(f"; {tag} begin {w}x{h} {len(b64)}")
        out += [f"; {b64[i:i + 78]}" for i in range(0, len(b64), 78)]
        out.append(f"; {tag} end")
        out.append(";")
    out.append("; THUMBNAIL_BLOCK_END")
    return "\n".join(out) + "\n"


def add_to_gcode(gcode: Path, machine: dict[str, Any], default_when_missing: bool = True) -> int:
    """Insert preview images into a sliced G-code file (in place); returns the number of images. Never raises:
    a G-code without pictures still prints."""
    try:
        wanted = specs(machine, default_when_missing)
        if not wanted:
            return 0
        with gcode.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(65536)
        if re.search(r"^; thumbnail(_\w+)? begin", head, re.M):
            return 0                                          # the slicer made some after all
        with gcode.open(encoding="utf-8", errors="replace") as fh:
            preview = gcode_preview.parse(fh)
        img = render(preview)
        if img is None:
            return 0
        text = blocks(img, wanted)
        tmp = gcode.with_suffix(".thumbs.tmp")
        with gcode.open("rb") as src, tmp.open("wb") as dst:
            inserted = False
            for line in src:
                dst.write(line)
                if not inserted and line.startswith(b"; HEADER_BLOCK_END"):
                    dst.write(b"\n" + text.encode())
                    inserted = True
                    break
            if not inserted:                                   # no header block: images go first
                dst.seek(0)
                dst.truncate()
                src.seek(0)
                dst.write(text.encode() + b"\n")
            shutil.copyfileobj(src, dst)
        tmp.replace(gcode)
        return len(wanted)
    except Exception:  # noqa: BLE001 - pictures are a nice-to-have
        log.exception("could not add thumbnails to %s", gcode)
        return 0
