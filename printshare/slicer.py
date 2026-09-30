"""Headless slicing with the OrcaSlicer command line."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import model_info, transform
from .config import PrinterConfig, Settings, SlicingConfig
from .profiles import ProfileLibrary, load_user_preset, write_preset
from .user_profiles import resolve_preset


class SliceError(RuntimeError):
    pass


@dataclass
class SliceResult:
    gcode_path: Path
    print_time: str | None = None
    filament_g: float | None = None
    filament_m: float | None = None
    layers: int | None = None
    log: str = ""
    warnings: list[str] = field(default_factory=list)
    filaments: list[dict] = field(default_factory=list)   # multicolour: per filament of the model
    copies: int | None = None       # copies that fit on the plate (only set when more than 1 was asked for)


_TIME_RE = re.compile(r";\s*(?:model printing time|estimated printing time \(normal mode\))\s*[:=]\s*([^;\n]+)")
_GRAMS_RE = re.compile(r";\s*(?:total filament weight \[g\]|filament used \[g\]|total filament used \[g\])\s*[:=]\s*([\d.]+)")
_METERS_RE = re.compile(r";\s*(?:total filament length \[mm\]|filament used \[mm\])\s*[:=]\s*([\d.]+)")
_LAYERS_RE = re.compile(r";\s*total layer number\s*[:=]\s*(\d+)")
_GRAMS_EACH_RE = re.compile(r";\s*filament used \[g\]\s*=\s*([\d., ]+)")


def filament_grams(gcode: Path) -> list[float]:
    """Per-filament weights from the G-code footer: '; filament used [g] = 1.23, 4.56'."""
    data = gcode.read_bytes()
    m = _GRAMS_EACH_RE.search(data[-200_000:].decode("utf-8", "ignore"))
    if not m:
        return []
    out = []
    for v in m.group(1).split(","):
        try:
            out.append(round(float(v), 2))
        except ValueError:
            pass
    return out


def _parse_estimates(gcode: Path) -> tuple[str | None, float | None, float | None, int | None]:
    data = gcode.read_bytes()
    text = data[:200_000].decode("utf-8", "ignore") + "\n" + data[-200_000:].decode("utf-8", "ignore")
    t = _TIME_RE.search(text)
    g = _GRAMS_RE.search(text)
    m = _METERS_RE.search(text)
    n = _LAYERS_RE.search(text)
    layers = int(n.group(1)) if n else (data.count(b"\n;LAYER_CHANGE") or None)
    return (
        t.group(1).strip() if t else None,
        float(g.group(1)) if g else None,
        round(float(m.group(1)) / 1000, 2) if m else None,
        layers,
    )


class Slicer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._library: ProfileLibrary | None = None

    @property
    def library(self) -> ProfileLibrary:
        if self._library is None:
            self._library = ProfileLibrary.cached(self.settings.orca_profiles_dir)
        return self._library

    def build_presets(self, printer: PrinterConfig, workdir: Path,
                      slicing: SlicingConfig | None = None,
                      colors: list[str] | None = None) -> tuple[Path, Path, list[Path]]:
        """Machine + process preset, and one filament preset per filament of the model.
        `colors` are the model's filament colours: they go into the presets so the G-code (and
        the app's preview) know them."""
        s = slicing or printer.slicing
        lib = self.library
        if s.machine_file:
            machine = load_user_preset(Path(s.machine_file), s.machine_overrides, lib, "machine")
        else:
            machine = lib.resolve("machine", s.machine, s.machine_overrides)
        cfg_dir = self.settings.config_dir or None        # uploaded process/filament presets (#2, #7)
        process = resolve_preset(lib, cfg_dir, "process", s.process, s.process_overrides)
        count = max(len(colors or []), len(s.filaments), 1)
        names = [(s.filaments[i] if i < len(s.filaments) else None) or s.filament for i in range(count)]
        filaments = []
        for i, name in enumerate(names):
            f = resolve_preset(lib, cfg_dir, "filament", name, s.filament_overrides)
            if colors and i < len(colors):
                f["filament_colour"] = [colors[i]]
            filaments.append(f)
        # Make sure the process/filament accept this machine even if it was renamed.
        mname = machine["name"]
        for preset in (process, *filaments):
            cp = preset.get("compatible_printers")
            if isinstance(cp, list) and cp and mname not in cp:
                preset["compatible_printers"] = cp + [mname]
        return (
            write_preset(machine, workdir / "machine.json"),
            write_preset(process, workdir / "process.json"),
            [write_preset(f, workdir / f"filament_{i + 1}.json") for i, f in enumerate(filaments)],
        )

    def slice(self, model: Path, printer: PrinterConfig, out_dir: Path,
              slicing: SlicingConfig | None = None) -> SliceResult:
        slicing = slicing or printer.slicing
        model = Path(model)
        out_dir.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="slice-", dir=self.settings.work_dir))
        try:
            info = model_info.inspect(model)
            colors = [f["color"] for f in info["filaments"]]
            m, p, fs = self.build_presets(printer, work, slicing, colors)
            source = model
            if transform.needed(slicing.rotate_x, slicing.rotate_y, slicing.scale):
                try:
                    source = transform.transform_model(model, work / "model", slicing.rotate_x,
                                                       slicing.rotate_y, slicing.scale)
                except transform.TransformError as e:
                    raise SliceError(str(e)) from e
            copies = max(1, slicing.copies)
            project = transform.is_orca_project(source)
            cmd = [
                self.settings.orca_binary,
                "--arrange", "1",
                "--orient", "1" if slicing.auto_orient else "0",
                "--ensure-on-bed",
                "--slice", str(slicing.plate),
                "--load-settings", f"{m};{p}",
                # by position: 1st file replaces the model's filament 1, … (OrcaSlicer CLI)
                "--load-filaments", ";".join(str(f) for f in fs),
                "--outputdir", str(work / "out"),
                "--export-3mf", "result.3mf",
            ]
            if model.suffix.lower() == ".3mf":
                cmd += ["--allow-newer-file"]
            if copies > 1 and project:
                # only OrcaSlicer/Bambu projects keep a plate for --repetitions; it fits as many as it can
                cmd += ["--repetitions", str(copies)]
                cmd.append(str(source))
            else:
                # other files: load the model once per copy; what does not fit goes to plates we don't slice
                cmd += [str(source)] * copies
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=work,
                                  timeout=self.settings.slice_timeout_s)
            log = (proc.stdout or "") + (proc.stderr or "")
            gcode_src = self._find_gcode(work / "out", slicing.plate)
            if gcode_src is None:
                tail = "\n".join(log.strip().splitlines()[-25:])
                if proc.returncode < 0:   # killed by a signal, e.g. -11 = segmentation fault
                    raise SliceError(f"OrcaSlicer crashed (signal {-proc.returncode}) - the model or project file "
                                     f"may be damaged or incomplete.\n{tail}")
                raise SliceError(f"OrcaSlicer produced no G-code (exit {proc.returncode}).\n{tail}")
            target = out_dir / f"{model.stem[:60]}.gcode"
            shutil.copyfile(gcode_src, target)
            t, g, mtr, layers = _parse_estimates(target)
            placed = None
            if copies > 1:
                total = transform.placed_objects(work / "out" / "result.3mf", slicing.plate if project else 1)
                if total is not None:
                    placed = max(1, total // transform.count_objects(source, slicing.plate))
            per = []
            if len(fs) > 1:
                grams = filament_grams(target)
                names = [(slicing.filaments[i] if i < len(slicing.filaments) else None) or slicing.filament
                         for i in range(len(fs))]
                per = [{"index": i + 1, "color": colors[i] if i < len(colors) else None, "preset": names[i],
                        "grams": grams[i] if i < len(grams) else None} for i in range(len(fs))]
            return SliceResult(target, t, g, mtr, layers, log, filaments=per, copies=placed)
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
