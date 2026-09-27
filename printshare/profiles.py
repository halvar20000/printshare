"""Resolve OrcaSlicer system presets into flat, self-contained JSON files.

OrcaSlicer's bundled presets use `inherits` chains (e.g. "Elegoo Centauri Carbon
0.4 nozzle" -> "fdm_elegoo_3dp_001_common" -> "fdm_machine_common"). The CLI is
far more reliable with fully flattened presets, so we merge the chain ourselves.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

KINDS = ("machine", "process", "filament")


class ProfileError(RuntimeError):
    pass


class ProfileLibrary:
    def __init__(self, profiles_dir: Path):
        self.profiles_dir = Path(profiles_dir)
        if not self.profiles_dir.is_dir():
            raise ProfileError(f"OrcaSlicer profiles directory not found: {self.profiles_dir}")
        # index[kind][name] = path ; vendor-local names win over other vendors
        self._index: dict[str, dict[str, Path]] = {k: {} for k in KINDS}
        for vendor_dir in sorted(p for p in self.profiles_dir.iterdir() if p.is_dir()):
            for kind in KINDS:
                kdir = vendor_dir / kind
                if not kdir.is_dir():
                    continue
                for f in kdir.rglob("*.json"):
                    try:
                        name = json.loads(f.read_text(encoding="utf-8")).get("name")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if name:
                        self._index[kind].setdefault(name, f)
        self._raw: dict[Path, dict[str, Any]] = {}
        self._compatible: dict[tuple[str, str], list[str]] = {}
        self._lock = threading.Lock()

    @classmethod
    def cached(cls, profiles_dir: str | Path) -> "ProfileLibrary":
        """Shared instance per directory; indexing thousands of presets takes a moment."""
        return _cached_library(str(profiles_dir))

    def _load(self, path: Path) -> dict[str, Any]:
        data = self._raw.get(path)
        if data is None:
            data = self._raw[path] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def names(self, kind: str, contains: str = "") -> list[str]:
        c = contains.lower()
        return sorted(n for n in self._index[kind] if c in n.lower())

    def resolve(self, kind: str, name: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a flattened preset (parents merged, child wins)."""
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        current: str | None = name
        while current:
            if current in seen:
                raise ProfileError(f"Inheritance loop at {current!r}")
            seen.add(current)
            path = self._index[kind].get(current)
            if path is None:
                hint = ", ".join(self.names(kind, name.split(" ")[0])[:8])
                raise ProfileError(f"{kind} preset {current!r} not found. Similar: {hint}")
            data = self._load(path)
            chain.append(data)
            current = data.get("inherits") or None

        merged: dict[str, Any] = {}
        for layer in reversed(chain):  # base first, leaf last
            merged.update(layer)
        merged.pop("inherits", None)
        merged["name"] = name
        merged["type"] = kind
        merged["from"] = "system"  # CLI only accepts compatible presets marked as system
        merged["instantiation"] = "true"
        if overrides:
            merged.update(overrides)
        return merged


    def compatible(self, kind: str, machine: str) -> list[str]:
        """User-selectable presets of `kind` whose compatible_printers include `machine`."""
        key = (kind, machine)
        with self._lock:
            if key not in self._compatible:
                found = []
                for name, path in self._index[kind].items():
                    if self._load(path).get("instantiation") == "false":
                        continue  # abstract base preset
                    try:
                        cp = self.resolve(kind, name).get("compatible_printers")
                    except ProfileError:
                        continue
                    if isinstance(cp, list) and machine in cp:
                        found.append(name)
                self._compatible[key] = sorted(found)
            return list(self._compatible[key])

    def value(self, kind: str, name: str, key: str) -> Any:
        return self.resolve(kind, name).get(key)


@lru_cache(maxsize=4)
def _cached_library(profiles_dir: str) -> ProfileLibrary:
    return ProfileLibrary(profiles_dir)


def load_user_preset(path: Path, overrides: dict[str, Any] | None = None,
                     library: ProfileLibrary | None = None, kind: str | None = None) -> dict[str, Any]:
    """Load a preset exported from the OrcaSlicer GUI (may still use `inherits`)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    parent = data.get("inherits")
    if parent and library is not None and kind:
        base = library.resolve(kind, parent)
        base.update({k: v for k, v in data.items() if k != "inherits"})
        data = base
    data.pop("inherits", None)
    data["from"] = "system"
    if overrides:
        data.update(overrides)
    return data


def write_preset(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
