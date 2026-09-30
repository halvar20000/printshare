"""Lane selection for multi-filament units (AFC on COSMOS/Klipper; issue #6, spec MA-02/03/04).

OrcaSlicer numbers the model's filaments T0, T1, … . Which physical lane prints which filament is chosen
in the app after slicing: at send time the tool numbers in the G-code are rewritten to the tool of the
chosen lane. The printer's own lane table (AFC `SET_MAP`) is left alone on purpose.
"""
from __future__ import annotations

import re
from pathlib import Path

_TOOL_LINE = re.compile(r"^T(\d+)(?=\s|;|$)")          # "T1", "T1 PURGE_LENGTH=20.8" (AFC)
_TOOL_PARAM = re.compile(r"(\bTOOL=)(\d+)")             # PRINT_START … TOOL=0
_M6211_T = re.compile(r"^(M6211\b.*?\bT)(\d+)")          # Elegoo CANVAS stock firmware


def remap_line(line: str, mapping: dict[int, int]) -> str:
    """Rewrite tool numbers in one G-code line; comments (incl. OrcaSlicer's settings dump) stay as they are."""
    if not line or line[0] == ";":
        return line
    code, sep, comment = line.partition(";")
    sub = lambda m: m.group(1) + str(mapping.get(int(m.group(2)), int(m.group(2))))  # noqa: E731
    code = _TOOL_LINE.sub(lambda m: "T" + str(mapping.get(int(m.group(1)), int(m.group(1)))), code)
    code = _TOOL_PARAM.sub(sub, code)
    code = _M6211_T.sub(sub, code)
    return code + sep + comment


def remap_tools(gcode: Path, mapping: dict[int, int], out_dir: Path) -> Path:
    """Copy of `gcode` with OrcaSlicer's tool numbers mapped to the printer's (same file name)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / gcode.name
    with gcode.open(encoding="utf-8", errors="surrogateescape", newline="") as src, \
            target.open("w", encoding="utf-8", errors="surrogateescape", newline="") as dst:
        for line in src:
            end = len(line) - len(line.rstrip("\r\n"))
            body = line[:len(line) - end] if end else line
            dst.write(remap_line(body, mapping) + line[len(body):])
    return target


def parse_mapping(lanes: dict[str, int] | None) -> dict[int, int]:
    """App request {"1": 2, "2": 0} (model filament -> printer tool) -> {0: 2, 1: 0} (Orca tool -> tool)."""
    out: dict[int, int] = {}
    for k, v in (lanes or {}).items():
        idx, tool = int(k), int(v)
        if not (1 <= idx <= 16 and 0 <= tool <= 63):
            raise ValueError("lane mapping out of range")
        out[idx - 1] = tool
    return out
