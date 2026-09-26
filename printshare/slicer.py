"""Headless slicing with the OrcaSlicer command line."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import PrinterConfig, Settings
from .profiles import ProfileLibrary, load_user_preset, write_preset


class SliceError(RuntimeError):
    pass


@dataclass
class SliceResult:
    gcode_path: Path
    print_time: str | None = None
    filament_g: float | None = None
    filament_m: float | None = None
    log: str = ""
    warnings: list[str] = field(default_factory=list)


_TIME_RE = re.compile(r";\s*(?:model printing time|estimated printing time \(normal mode\))\s*[:=]\s*([^;\n]+)")
_GRAMS_RE = re.compile(r";\s*(?:total filament weight \[g\]|filament used \[g\]|total filament used \[g\])\s*[:=]\s*([\d.]+)")
_METERS_RE = re.compile(r";\s*(?:total filament length \[mm\]|filament used \[mm\])\s*[:=]\s*([\d.]+)")


def _parse_estimates(gcode: Path) -> tuple[str | None, float | None, float | None]:
    head = gcode.read_bytes()[:200_000].decode("utf-8", "ignore")
    tail_bytes = gcode.read_bytes()[-200_000:].decode("utf-8", "ignore")
    text = head + "\n" + tail_bytes
    t = _TIME_RE.search(text)
    g = _GRAMS_RE.search(text)
    m = _METERS_RE.search(text)
    return (
        t.group(1).strip() if t else None,
        float(g.group(1)) if g else None,
        round(float(m.group(1)) / 1000, 2) if m else None,
    )


class Slicer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._library: ProfileLibrary | None = None

    @property
    def library(self) -> ProfileLibrary:
        if self._library is None:
            self._library = ProfileLibrary(self.settings.orca_profiles_dir)
        return self._library

    def build_presets(self, printer: PrinterConfig, workdir: Path) -> tuple[Path, Path, Path]:
        s = printer.slicing
        lib = self.library
        if s.machine_file:
            machine = load_user_preset(Path(s.machine_file), s.machine_overrides, lib, "machine")
        else:
            machine = lib.resolve("machine", s.machine, s.machine_overrides)
        process = lib.resolve("process", s.process, s.process_overrides)
        filament = lib.resolve("filament", s.filament, s.filament_overrides)
        # Make sure the process/filament accept this machine even if it was renamed.
        mname = machine["name"]
        for preset in (process, filament):
            cp = preset.get("compatible_printers")
            if isinstance(cp, list) and cp and mname not in cp:
                preset["compatible_printers"] = cp + [mname]
        return (
            write_preset(machine, workdir / "machine.json"),
            write_preset(process, workdir / "process.json"),
            write_preset(filament, workdir / "filament.json"),
        )

    def slice(self, model: Path, printer: PrinterConfig, out_dir: Path) -> SliceResult:
        model = Path(model)
        out_dir.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="slice-", dir=self.settings.work_dir))
        try:
            m, p, f = self.build_presets(printer, work)
            cmd = [
                self.settings.orca_binary,
                "--arrange", "1",
                "--orient", "1" if printer.slicing.auto_orient else "0",
                "--ensure-on-bed",
                "--slice", str(printer.slicing.plate),
                "--load-settings", f"{m};{p}",
                "--load-filaments", str(f),
                "--outputdir", str(work / "out"),
                "--export-3mf", "result.3mf",
            ]
            if model.suffix.lower() == ".3mf":
                cmd += ["--allow-newer-file"]
            cmd.append(str(model))
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=work,
                                  timeout=self.settings.slice_timeout_s)
            log = (proc.stdout or "") + (proc.stderr or "")
            gcode_src = self._find_gcode(work / "out", printer.slicing.plate)
            if gcode_src is None:
                tail = "\n".join(log.strip().splitlines()[-25:])
                raise SliceError(f"OrcaSlicer produced no G-code (exit {proc.returncode}).\n{tail}")
            target = out_dir / f"{model.stem[:60]}.gcode"
            shutil.copyfile(gcode_src, target)
            t, g, mtr = _parse_estimates(target)
            return SliceResult(target, t, g, mtr, log)
        finally:
            if not self.settings.keep_work_files:
                shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _find_gcode(out: Path, plate: int) -> Path | None:
        if not out.exists():
            return None
        plain = sorted(out.rglob("*.gcode"))
        if plain:
            return plain[0]
        three_mf = out / "result.3mf"
        if three_mf.exists():
            with zipfile.ZipFile(three_mf) as z:
                wanted = f"Metadata/plate_{max(plate, 1)}.gcode"
                names = z.namelist()
                name = wanted if wanted in names else next(
                    (n for n in names if n.startswith("Metadata/plate_") and n.endswith(".gcode")), None)
                if name:
                    dest = out / Path(name).name
                    dest.write_bytes(z.read(name))
                    return dest
        return None
