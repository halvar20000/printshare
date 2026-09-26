"""Configuration (config.yaml) for PrintShare."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Start/end G-code required by OpenCentauri COSMOS (>= 26.07.0). The stock Elegoo
# macros M729 / M8213 trigger an emergency stop on COSMOS on purpose.
COSMOS_OVERRIDES: dict[str, Any] = {
    "machine_start_gcode": (
        "PRINT_START EXTRUDER=[nozzle_temperature_initial_layer] "
        "BED=[bed_temperature_initial_layer_single] CHAMBER=[chamber_temperature]\n"
    ),
    "machine_end_gcode": "PRINT_END\n",
}

PRESETS: dict[str, dict[str, Any]] = {"cosmos": COSMOS_OVERRIDES}


@dataclass
class SlicingConfig:
    machine: str = "Elegoo Centauri Carbon 0.4 nozzle"
    process: str = "0.20mm Standard @Elegoo CC 0.4 nozzle"
    filament: str = "Elegoo PLA @ECC"
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
        if self.machine_preset:
            base = dict(PRESETS.get(self.machine_preset, {}))
            if not base:
                raise ValueError(f"Unknown machine_preset {self.machine_preset!r}")
            base.update(self.machine_overrides)
            self.machine_overrides = base


@dataclass
class PrinterConfig:
    id: str
    type: str                     # "elegoo_sdcp" | "moonraker"
    name: str = ""
    host: str | None = None       # elegoo_sdcp
    url: str | None = None        # moonraker, e.g. http://192.168.1.60 or http://host:7125
    api_key: str | None = None    # moonraker (optional)
    auto_leveling: bool = True    # elegoo_sdcp
    slicing: SlicingConfig = field(default_factory=SlicingConfig)


@dataclass
class Settings:
    api_token: str = ""
    orca_binary: str = "/opt/orca/AppRun"
    orca_profiles_dir: str = "/opt/orca/resources/profiles"
    work_dir: str = "/data/work"
    gcode_dir: str = "/data/gcode"
    thingiverse_token: str = ""
    slice_timeout_s: int = 900
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


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or os.environ.get("PRINTSHARE_CONFIG", "/config/config.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    printers = []
    for p in raw.pop("printers", []) or []:
        slicing = SlicingConfig(**(p.pop("slicing", {}) or {}))
        printers.append(PrinterConfig(slicing=slicing, **p))
    s = Settings(printers=printers, **raw)
    s.api_token = os.environ.get("PRINTSHARE_API_TOKEN", s.api_token)
    s.thingiverse_token = os.environ.get("THINGIVERSE_TOKEN", s.thingiverse_token)
    for d in (s.work_dir, s.gcode_dir):
        Path(d).mkdir(parents=True, exist_ok=True)
    return s
