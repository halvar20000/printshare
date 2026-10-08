"""Moving the printer by hand (0.43.0): home, jog the axes, extrude / retract, filament, motors off, macros.

One shape for every adapter: `adapter.motion()` says what the printer can do (`caps`), `adapter.move(action, …)` does
it. Actions:
- "home"    axis: one of caps["home"] ("XYZ" = all)
- "jog"     axis X/Y/Z, distance in mm (±, one of caps["jog"]["steps"] or less)
- "extrude" distance in mm (negative = retract)
- "load" / "unload"   heat the nozzle to `temp` (from the material), then pull filament in / push it out
- "motors_off"
- "macro"   macro: one of caps["macros"] (Klipper)

Never while a print runs (the API checks the printer state first). What each printer gets:
- Centauri Carbon (stock firmware, SDCP): Cmd 402 {"Axis": "X"|"Y"|"Z"|"XYZ"} = home, Cmd 401 {"Axis", "Step": ±mm}
  = jog - read from the printer's own web page (`cbdsa-mainboard-cmp`, chunk 590: `changeZore`, `changeAxis`,
  steps 0.1/1/10/100). The protocol has no extrude / load / unload command: load / unload are a tiny G-code file
  (`filament_gcode`, name FILE_PREFIX…) uploaded and started like a print, without bed levelling.
- Klipper (Moonraker): G28, G91 + G1 + G90, M83 + G1 E, M84; load/unload = M109 + LOAD_FILAMENT / UNLOAD_FILAMENT when
  the printer has those macros, else `filament_gcode`; other macros without a leading "_" as buttons (minus SKIP_MACROS).
- Bambu Lab: gcode_line like Bambu Studio's axis control (soft limits on for the jog: M211, push/pop ref mode),
  extrude M83 + G0 E; load (slot from caps["load_slots"]) / unload through the AMS change with the temperature.
"""
from __future__ import annotations

ACTIONS = ("home", "jog", "extrude", "load", "unload", "motors_off", "macro")
AXES = ("X", "Y", "Z")
FEED = {"X": 3000, "Y": 3000, "Z": 600}           # mm/min for jogging
EXTRUDE_FEED = 300
MAX_EXTRUDE = 100.0
# macros that are not buttons: started by print files, restarting the printer, or already elsewhere in the app
SKIP_MACROS = {
    "PRINT_START", "PRINT_END", "START_PRINT", "END_PRINT", "CANCEL_PRINT", "PAUSE", "RESUME", "SAVE_CONFIG",
    "REBOOT_MACHINE", "FIRMWARE_RESTART", "RESTART", "SET_PRINT_STATS_INFO", "SET_PAUSE_NEXT_LAYER",
    "SET_PAUSE_AT_LAYER", "SET_DISPLAY_TEXT", "LOAD_FILAMENT", "UNLOAD_FILAMENT", "DOOM", "SET_LED",
}


FILE_PREFIX = "pp3d-filament-"     # Centauri load/unload files: not shown as jobs, no time-lapse
DEFAULT_TEMP = 220
LOAD_MM, LOAD_FEED = 90, 240        # pull in slowly: the user still pushes the filament into the extruder
UNLOAD_PUSH, UNLOAD_TIP, UNLOAD_MM = 10, 20, 80
# Klipper (also inside the Centauri's stock firmware) refuses an extrude-only move longer than max_extrude_only_distance
# (default 50 mm) and drops the rest of the file: the nozzle heated, but the filament never moved (Thomas' CC, 2026-10-08)
MAX_E_MOVE = 25


def _e_moves(mm: float, feed: int) -> str:
    """One extrude (mm > 0) or retract (mm < 0) split into moves of at most MAX_E_MOVE mm."""
    out, left = [], abs(mm)
    while left > 1e-9:
        step = min(left, MAX_E_MOVE)
        out.append(f"G1 E{'-' if mm < 0 else ''}{step:g} F{feed}\n")
        left -= step
    return "".join(out)


def filament_gcode(action: str, temp: int) -> str:
    """Heat, then pull the filament in (load) or push a little and pull it out (unload, shaped tip); nozzle off at the
    end. Used as a script (Klipper) or as a file started like a print (Centauri)."""
    head = f"; PocketPrint3D filament {action} at {temp} C\nM104 S{temp}\nM109 S{temp}\nM83\nG92 E0\n"
    if action == "load":
        body = _e_moves(LOAD_MM, LOAD_FEED)
    else:
        body = _e_moves(UNLOAD_PUSH, 300) + _e_moves(-UNLOAD_TIP, 2400) + _e_moves(-UNLOAD_MM, 1200)
    return head + body + "M400\nM104 S0\n"


def is_filament_file(name: str | None) -> bool:
    from pathlib import Path
    return bool(name) and Path(str(name)).name.startswith(FILE_PREFIX)


class MotionError(ValueError):
    pass


def check(caps: dict, action: str, axis: str | None = None, distance: float | None = None,
          macro: str | None = None, slot: int | None = None) -> None:
    """Raise MotionError when the printer can't do this (caps from adapter.motion())."""
    if action not in ACTIONS:
        raise MotionError(f"action must be one of {', '.join(ACTIONS)}")
    if action == "home":
        if axis not in (caps.get("home") or []):
            raise MotionError(f"home: axis must be one of {', '.join(caps.get('home') or []) or '-'}")
    elif action == "jog":
        jog = caps.get("jog") or {}
        if axis not in (jog.get("axes") or []):
            raise MotionError("this printer can't move that axis from PocketPrint3D")
        biggest = max(jog.get("steps") or [0])
        if distance is None or distance == 0 or abs(distance) > biggest:
            raise MotionError(f"distance must be between -{biggest:g} and {biggest:g} mm (not 0)")
    elif action == "extrude":
        if not caps.get("extrude"):
            raise MotionError("this printer can't extrude from PocketPrint3D")
        if distance is None or distance == 0 or abs(distance) > MAX_EXTRUDE:
            raise MotionError(f"distance must be between -{MAX_EXTRUDE:g} and {MAX_EXTRUDE:g} mm (not 0)")
    elif action == "macro":
        if macro not in (caps.get("macros") or []):
            raise MotionError("unknown macro")
    elif action == "load" and caps.get("load_slots") is not None:
        if not caps.get("load"):
            raise MotionError("this printer can't load filament from PocketPrint3D")
        if slot not in {s.get("tool") for s in caps["load_slots"]}:
            raise MotionError("which slot to load? (slot)")
    elif not caps.get(action):
        raise MotionError(f"this printer can't {action.replace('_', ' ')} from PocketPrint3D")


# ---------- G-code for Klipper and Bambu ----------
def home_gcode(axis: str) -> str:
    return "G28" if axis == "XYZ" else f"G28 {axis}"


def jog_gcode(axis: str, distance: float) -> str:
    return f"G91\nG1 {axis}{distance:g} F{FEED[axis]}\nG90"


def extrude_gcode(distance: float) -> str:
    return f"M83\nG1 E{distance:g} F{EXTRUDE_FEED}"


def bambu_jog(axis: str, distance: float) -> str:
    # as Bambu Studio sends it: soft limits on, relative move, back to the previous mode
    return (f"M211 S \nM211 X1 Y1 Z1\nM1002 push_ref_mode\nG91 \nG1 {axis}{distance:.1f} F{FEED[axis]}\n"
            "M1002 pop_ref_mode\nM211 R\n")


def klipper_macros(objects: list[str]) -> list[str]:
    """User macros of a Klipper printer (object "gcode_macro NAME"), without hidden ones (leading "_") and plain G/M codes."""
    out = []
    for o in objects:
        if not o.lower().startswith("gcode_macro "):
            continue
        name = o.split(" ", 1)[1].strip()
        up = name.upper()
        if not name or name.startswith("_") or up in SKIP_MACROS or (up[:1] in "GMT" and up[1:].isdigit()):
            continue
        out.append(up)
    return sorted(set(out))
