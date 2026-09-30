"""Configuration (config.yaml) for PrintShare."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Start/end G-code required by OpenCentauri COSMOS (>= 26.07.0). The stock Elegoo
# macros M729 / M8213 trigger an emergency stop on COSMOS on purpose.
# Multicolour (CANVAS via AFC) as in Dominique's COSMOS AFC OrcaSlicer profile (2026-09-29): AFC does the
# tool change (T<n> PURGE_LENGTH=…) instead of Elegoo's M6211, PRINT_START gets the first tool, and
# OrcaSlicer's own ramming/parking moves are switched off because AFC loads and unloads itself.
COSMOS_OVERRIDES: dict[str, Any] = {
    "machine_start_gcode": (
        "M104 S0 ; stops OrcaSlicer from sending temperature waits separately\n"
        "M140 S0\n"
        "SET_PRINT_STATS_INFO TOTAL_LAYER=[total_layer_count]\n"
        "PRINT_START EXTRUDER=[nozzle_temperature_initial_layer] "
        "BED=[bed_temperature_initial_layer_single] CHAMBER=[chamber_temperature] TOOL={initial_tool}\n"
    ),
    "machine_end_gcode": "PRINT_END\n",
    "machine_pause_gcode": "PAUSE",
    "change_filament_gcode": (
        "T[next_extruder] PURGE_LENGTH=[flush_length]\n"
        "; FLUSH_START\n"
        "; EXTERNAL_PURGE {flush_length_1+flush_length_2+flush_length_3+flush_length_4}\n"
        "; FLUSH_END"
    ),
    "cooling_tube_length": "0",
    "cooling_tube_retraction": "0",
    "extra_loading_move": "0",
    "parking_pos_retraction": "0",
}

PRESETS: dict[str, dict[str, Any]] = {"cosmos": COSMOS_OVERRIDES}


@dataclass
class SlicingConfig:
    machine: str = "Elegoo Centauri Carbon 0.4 nozzle"
    process: str = "0.20mm Standard @Elegoo CC 0.4 nozzle"
    filament: str = "Elegoo PLA @ECC"
    # multicolour: one filament preset per filament of the model (index 0 = filament 1); empty = `filament`
    filaments: list[str] = field(default_factory=list)
    machine_file: str | None = None          # preset exported from the OrcaSlicer GUI
    machine_preset: str | None = None        # e.g. "cosmos"
    machine_overrides: dict[str, Any] = field(default_factory=dict)
    process_overrides: dict[str, Any] = field(default_factory=dict)
    filament_overrides: dict[str, Any] = field(default_factory=dict)
    plate: int = 1
    auto_orient: bool = False
    # Build plate; the CLI otherwise defaults to "Cool Plate" (35 °C for PLA).
    # Options: "Textured PEI Plate", "High Temp Plate", "Cool Plate", "Engineering Plate", "Supertack Plate"
    bed_type: str = "Textured PEI Plate"

    def __post_init__(self) -> None:
        self.process_overrides = {"curr_bed_type": self.bed_type, **self.process_overrides}
        if self.machine_preset and self.machine_file and _has_print_start(self.machine_file):
            # the user's own printer preset already has the Klipper start code (e.g. an AFC COSMOS preset):
            # don't replace it with the built-in one (issue #2)
            self.machine_preset = None
        if self.machine_preset:
            base = dict(PRESETS.get(self.machine_preset, {}))
            if not base:
                raise ValueError(f"Unknown machine_preset {self.machine_preset!r}")
            base.update(self.machine_overrides)
            self.machine_overrides = base


def _has_print_start(machine_file: str) -> bool:
    try:
        data = json.loads(Path(machine_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    start = data.get("machine_start_gcode") or ""
    return "PRINT_START" in ("\n".join(start) if isinstance(start, list) else str(start))


SUPPORT_TYPES = {"normal": "normal(auto)", "tree": "tree(auto)"}
BRIM_TYPES = {"auto": "auto_brim", "off": "no_brim", "outer": "outer_only"}


@dataclass
class JobOptions:
    """Per-job choices from the app; None keeps the printer's configured value."""
    filament: str | None = None
    process: str | None = None
    bed_type: str | None = None
    supports: str | None = None   # "off" | "normal" | "tree"
    brim: str | None = None       # "auto" | "off" | "outer"
    infill: int | None = None     # sparse infill density in percent
    walls: int | None = None      # wall loops
    # multicolour: preset per filament of the model (1st = filament 1); None entries use `filament`
    filaments: list[str | None] | None = None

    def process_overrides(self) -> dict[str, Any]:
        o: dict[str, Any] = {}
        if self.supports == "off":
            o["enable_support"] = "0"
        elif self.supports is not None:
            if self.supports not in SUPPORT_TYPES:
                raise ValueError(f"supports must be off, {', '.join(SUPPORT_TYPES)}")
            o.update(enable_support="1", support_type=SUPPORT_TYPES[self.supports])
        if self.brim is not None:
            if self.brim not in BRIM_TYPES:
                raise ValueError(f"brim must be one of {', '.join(BRIM_TYPES)}")
            o["brim_type"] = BRIM_TYPES[self.brim]
        if self.infill is not None:
            if not 0 <= self.infill <= 100:
                raise ValueError("infill must be 0-100 %")
            o["sparse_infill_density"] = f"{self.infill}%"
        if self.walls is not None:
            if not 1 <= self.walls <= 20:
                raise ValueError("walls must be 1-20")
            o["wall_loops"] = str(self.walls)
        return o

    def apply(self, base: SlicingConfig) -> SlicingConfig:
        """Return a copy of `base` with these options applied (base stays untouched)."""
        s = copy.copy(base)  # no __post_init__: overrides are already merged in `base`
        s.filament = self.filament or base.filament
        s.filaments = [f or s.filament for f in self.filaments] if self.filaments else list(base.filaments)
        s.process = self.process or base.process
        s.bed_type = self.bed_type or base.bed_type
        s.process_overrides = {**base.process_overrides, "curr_bed_type": s.bed_type,
                               **self.process_overrides()}
        return s


@dataclass
class PrinterConfig:
    id: str
    type: str                     # "elegoo_sdcp" | "moonraker" | "prusalink" | "octoprint"
    name: str = ""
    host: str | None = None       # elegoo_sdcp
    url: str | None = None        # moonraker / prusalink / octoprint, e.g. http://192.168.1.60
    api_key: str | None = None    # moonraker (optional), octoprint (required), prusalink (older firmware)
    username: str = "maker"       # prusalink (HTTP digest), shown on the printer's screen
    password: str | None = None   # prusalink
    auto_leveling: bool = True    # elegoo_sdcp
    mainboard_id: str | None = None  # elegoo_sdcp; looked up via UDP discovery if not set
    slicing: SlicingConfig = field(default_factory=SlicingConfig)


@dataclass
class Settings:
    api_token: str = ""
    config_dir: str = ""           # folder of config.yaml (profiles/ and printers.d/ live there)
    orca_binary: str = "/opt/orca/AppRun"
    orca_profiles_dir: str = "/opt/orca/resources/profiles"
    work_dir: str = "/data/work"
    gcode_dir: str = "/data/gcode"
    thingiverse_token: str = ""
    slice_timeout_s: int = 900
    max_parallel_slices: int = 1   # BE-01: further slice jobs wait in a queue
    keep_work_files: bool = False
    printers: list[PrinterConfig] = field(default_factory=list)

    def printer(self, printer_id: str | None) -> PrinterConfig:
        if not self.printers:
            raise KeyError("No printers configured")
        if printer_id is None:
            return self.printers[0]
        for p in self.printers:
            if p.id == printer_id:
                return p
        raise KeyError(f"Unknown printer {printer_id!r}. Known: {[p.id for p in self.printers]}")


def _machine_defaults(sl: dict[str, Any], profiles_dir: str, printer_id: str) -> None:
    """Printers other than the Centauri Carbon: take quality and filament from the machine preset's own
    defaults (default_print_profile / default_filament_profile) unless they are set explicitly, so a
    Prusa never gets the Centauri presets by accident."""
    machine = sl.get("machine")
    if not machine or machine == SlicingConfig.machine or sl.get("machine_file"):
        return
    missing = [k for k in ("process", "filament") if not sl.get(k)]
    if not missing:
        return
    from .profiles import ProfileError, ProfileLibrary
    try:
        preset = ProfileLibrary.cached(profiles_dir).resolve("machine", machine)
    except ProfileError as e:
        raise ValueError(f"Printer {printer_id}: {e}") from e
    for key, field_name in (("process", "default_print_profile"), ("filament", "default_filament_profile")):
        if key in missing:
            value = preset.get(field_name)
            if isinstance(value, list):
                value = value[0] if value else None
            if isinstance(value, str):
                value = value.split(";")[0].strip()
            if not value:
                raise ValueError(f"Printer {printer_id}: set slicing.{key} - OrcaSlicer's {machine!r} has no default")
            sl[key] = value


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or os.environ.get("PRINTSHARE_CONFIG", "/config/config.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    printers = []
    profiles_dir = raw.get("orca_profiles_dir", Settings.orca_profiles_dir)
    config_dir = path.parent
    raw.setdefault("config_dir", str(config_dir))
    for p in raw.pop("printers", []) or []:
        sl = dict(p.pop("slicing", {}) or {})
        # settings made in the app (printers.d/<id>.yaml) win over config.yaml, which the Unraid template /
        # Home Assistant add-on may regenerate on every start
        overlay_file = config_dir / "printers.d" / f"{p.get('id')}.yaml"
        if overlay_file.is_file():
            sl.update((yaml.safe_load(overlay_file.read_text(encoding="utf-8")) or {}).get("slicing") or {})
        mf = sl.get("machine_file")
        if mf and not Path(mf).is_absolute():
            sl["machine_file"] = str(config_dir / "profiles" / mf)     # uploaded preset: stored by name
        _machine_defaults(sl, profiles_dir, p.get("id", "?"))
        printers.append(PrinterConfig(slicing=SlicingConfig(**sl), **p))
    s = Settings(printers=printers, **raw)
    # empty variables (e.g. unused fields of the Unraid template) must not clear the token
    s.api_token = os.environ.get("PRINTSHARE_API_TOKEN") or s.api_token
    s.thingiverse_token = os.environ.get("THINGIVERSE_TOKEN") or s.thingiverse_token
    for d in (s.work_dir, s.gcode_dir):
        Path(d).mkdir(parents=True, exist_ok=True)
    return s
