"""User presets from OrcaSlicer, uploaded through the app (issue #2, spec PR-01/02).

* Upload: a preset exported from OrcaSlicer (JSON, may use `inherits`) or a preset bundle
  (.zip / .orca_printer / .orca_filament with several JSON files). Checked before it is stored:
  valid JSON object, known kind (printer / process / filament), `inherits` resolvable in the
  bundled OrcaSlicer system presets. Stored in <config dir>/profiles/.
* Assignment: which uploaded printer preset a printer uses is kept in
  <config dir>/printers.d/<printer id>.yaml. config.load_settings applies these files on every start,
  so they survive the regenerated config.yaml of the Unraid template / Home Assistant add-on.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import yaml

from .profiles import ProfileError, ProfileLibrary, load_user_preset

PROFILES_DIR = "profiles"
OVERLAY_DIR = "printers.d"
MAX_UPLOAD = 5 * 1024 * 1024
KINDS = ("machine", "process", "filament")
BUNDLE_SUFFIXES = (".zip", ".orca_printer", ".orca_filament", ".orca_bundle")


class ProfileUploadError(ValueError):
    pass


def profiles_dir(config_dir: str | Path) -> Path:
    return Path(config_dir) / PROFILES_DIR


def overlay_path(config_dir: str | Path, printer_id: str) -> Path:
    return Path(config_dir) / OVERLAY_DIR / f"{printer_id}.yaml"


def detect_kind(data: dict[str, Any]) -> str | None:
    t = str(data.get("type") or "").lower()
    if t in KINDS:
        return t
    if t == "printer":
        return "machine"
    if any(k in data for k in ("printer_settings_id", "machine_start_gcode", "printable_area", "printer_model")):
        return "machine"
    if any(k in data for k in ("filament_settings_id", "filament_type", "nozzle_temperature")):
        return "filament"
    if any(k in data for k in ("print_settings_id", "wall_loops", "sparse_infill_density", "layer_height")):
        return "process"
    return None


def _safe_file(name: str) -> str:
    stem = re.sub(r"[^\w.\- ]+", "_", name).strip(" ._") or "profile"
    return stem[:120] + ".json"


def _system_base(data: dict[str, Any], kind: str, lib: ProfileLibrary) -> str | None:
    """Nearest parent that is a bundled OrcaSlicer system preset (used for compatible presets)."""
    parent = data.get("inherits")
    if not parent:
        return None
    try:
        lib.resolve(kind, parent)
    except ProfileError as e:
        raise ProfileUploadError(f"{data.get('name', 'preset')!r} is based on {parent!r}, which OrcaSlicer 2.4.2 "
                                 f"on the server does not know. ({e})") from e
    return parent


def summary(data: dict[str, Any], kind: str, lib: ProfileLibrary, file: str | None = None) -> dict[str, Any]:
    base = _system_base(data, kind, lib)
    start = data.get("machine_start_gcode") or ""
    if isinstance(start, list):
        start = "\n".join(start)
    out: dict[str, Any] = {"file": file, "kind": kind, "name": data.get("name"), "inherits": base}
    if kind == "machine":
        out["print_start"] = "PRINT_START" in start
        nozzle = data.get("nozzle_diameter")
        out["nozzle"] = (nozzle[0] if isinstance(nozzle, list) and nozzle else nozzle) or None
    return out


def _parse(filename: str, content: bytes) -> list[dict[str, Any]]:
    if not content:
        raise ProfileUploadError("empty file")
    if len(content) > MAX_UPLOAD:
        raise ProfileUploadError(f"file too large (max {MAX_UPLOAD // 1048576} MB)")
    lower = filename.lower()
    blobs: list[tuple[str, bytes]] = []
    if lower.endswith(BUNDLE_SUFFIXES) or content[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                for n in z.namelist():
                    if n.lower().endswith(".json") and not n.endswith("bundle_structure.json") and not n.endswith("/"):
                        blobs.append((n, z.read(n)))
        except zipfile.BadZipFile as e:
            raise ProfileUploadError("not a valid preset bundle (zip)") from e
        if not blobs:
            raise ProfileUploadError("the bundle contains no presets")
    else:
        blobs.append((filename, content))
    presets = []
    for n, raw in blobs:
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ProfileUploadError(f"{Path(n).name}: not a valid JSON preset ({e})") from e
        if not isinstance(data, dict):
            raise ProfileUploadError(f"{Path(n).name}: not an OrcaSlicer preset")
        data.setdefault("name", Path(n).stem)
        presets.append(data)
    return presets


def store(config_dir: str | Path, filename: str, content: bytes, lib: ProfileLibrary) -> list[dict[str, Any]]:
    """Check and store an uploaded preset or bundle. Returns a summary per stored preset."""
    return store_presets(config_dir, _parse(filename, content), lib)


def store_presets(config_dir: str | Path, presets: list[dict[str, Any]], lib: ProfileLibrary) -> list[dict[str, Any]]:
    """Check presets (all must be usable, else nothing is stored) and store them."""
    checked = []
    for data in presets:
        kind = detect_kind(data)
        if kind is None:
            raise ProfileUploadError(f"{data.get('name')!r}: can't tell whether this is a printer, process "
                                     "or filament preset")
        info = summary(data, kind, lib)        # raises when `inherits` is unknown
        checked.append((data, kind, info))
    target = profiles_dir(config_dir)
    target.mkdir(parents=True, exist_ok=True)
    out = []
    for data, kind, info in checked:
        data = {k: v for k, v in data.items() if k not in ("print_host", "printhost_apikey", "printer_agent")}
        data["type"] = kind        # Orca Cloud says "printer"; the Orca CLI only reads "machine" (#7)
        file = _safe_file(f"{kind}-{data['name']}")
        (target / file).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        out.append({**info, "file": file})
    return out


def list_profiles(config_dir: str | Path, lib: ProfileLibrary) -> list[dict[str, Any]]:
    out = []
    d = profiles_dir(config_dir)
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            kind = detect_kind(data) or "unknown"
            info = summary(data, kind, lib, f.name) if kind in KINDS else {"file": f.name, "kind": kind}
        except (ValueError, ProfileUploadError) as e:
            info = {"file": f.name, "kind": "unknown", "error": str(e)}
        out.append(info)
    return out


def user_presets(config_dir: str | Path | None, kind: str) -> dict[str, Path]:
    """Uploaded presets of one kind by their name - process and filament presets are chosen by name in the
    app like system presets (later also the ones synced from Orca Cloud, #7)."""
    d = profiles_dir(config_dir) if config_dir else None
    out: dict[str, Path] = {}
    for f in sorted(d.glob(f"{kind}-*.json")) if d and d.is_dir() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and detect_kind(data) == kind and data.get("name"):
            out.setdefault(str(data["name"]), f)
    return out


def resolve_preset(lib: ProfileLibrary, config_dir: str | Path | None, kind: str, name: str,
                   overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """A flattened preset: an uploaded one (its `inherits` resolved against the bundled system presets)
    if one has that name, else the OrcaSlicer system preset."""
    path = user_presets(config_dir, kind).get(name)
    if path is None:
        return lib.resolve(kind, name, overrides)
    data = load_user_preset(path, None, lib, kind)
    data.update(name=name, type=kind, instantiation="true")
    if overrides:
        data.update(overrides)
    return data


def compatible_user_presets(lib: ProfileLibrary, config_dir: str | Path | None, kind: str,
                            machines: list[str]) -> list[str]:
    """Uploaded process/filament presets usable on a printer: no printer list (= all) or one of `machines`."""
    out = []
    for name in user_presets(config_dir, kind):
        try:
            cp = resolve_preset(lib, config_dir, kind, name).get("compatible_printers")
        except (ProfileError, ValueError):
            continue                    # base not in OrcaSlicer 2.4.2: shown with its error in the list
        if not cp or (isinstance(cp, list) and any(m in cp for m in machines)):
            out.append(name)
    return sorted(out, key=str.lower)


def resolve_file(config_dir: str | Path, file: str) -> Path:
    """Only plain file names inside the profiles folder (no paths from the outside)."""
    if not re.fullmatch(r"[\w.\- ]+\.json", file) or file.startswith("."):
        raise ProfileUploadError("invalid profile name")
    path = profiles_dir(config_dir) / file
    if not path.is_file():
        raise ProfileUploadError(f"profile {file!r} not found")
    return path


def read_overlay(config_dir: str | Path, printer_id: str) -> dict[str, Any]:
    p = overlay_path(config_dir, printer_id)
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def assign_machine(config_dir: str | Path, printer_id: str, file: str | None, lib: ProfileLibrary) -> dict[str, Any]:
    """Use an uploaded printer preset for a printer (None = back to the configured / system preset)."""
    overlay = read_overlay(config_dir, printer_id)
    slicing = dict(overlay.get("slicing") or {})
    for k in ("machine_file", "machine"):
        slicing.pop(k, None)
    if file:
        data = json.loads(resolve_file(config_dir, file).read_text(encoding="utf-8"))
        if detect_kind(data) != "machine":
            raise ProfileUploadError(f"{file!r} is not a printer preset")
        slicing["machine_file"] = file
        base = _system_base(data, "machine", lib)
        if base:
            slicing["machine"] = base      # compatible process/filament presets are those of the base printer
    if slicing:
        overlay["slicing"] = slicing
    else:
        overlay.pop("slicing", None)
    write_overlay(config_dir, printer_id, overlay)
    return overlay


def write_overlay(config_dir: str | Path, printer_id: str, overlay: dict[str, Any]) -> None:
    """Store a printer's app settings (slicing, power); owner-only, it can hold the Home Assistant token."""
    p = overlay_path(config_dir, printer_id)
    if not overlay:
        if p.exists():
            p.unlink()
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("# Set from the PocketPrint3D app / web page - kept when config.yaml is regenerated.\n"
                   + yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(p)


def delete(config_dir: str | Path, file: str, printer_ids: list[str]) -> None:
    path = resolve_file(config_dir, file)
    used = [pid for pid in printer_ids
            if (read_overlay(config_dir, pid).get("slicing") or {}).get("machine_file") == file]
    if used:
        raise ProfileUploadError(f"profile is in use by printer(s) {', '.join(used)} - choose another profile there first")
    path.unlink()
