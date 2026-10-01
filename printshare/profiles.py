"""Resolve OrcaSlicer system presets into flat, self-contained JSON files.

OrcaSlicer's bundled presets use `inherits` chains (e.g. "Elegoo Centauri Carbon
0.4 nozzle" -> "fdm_elegoo_3dp_001_common" -> "fdm_machine_common"). The CLI is
far more reliable with fully flattened presets, so we merge the chain ourselves.
"""
from __future__ import annotations

import json
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

KINDS = ("machine", "process", "filament")


class ProfileError(RuntimeError):
    pass


_TERM = re.compile(r"\s*(?:(?P<re>\w+)\s*(?P<rop>=~|!~)\s*/(?P<rx>[^/]*)/"
                   r"|(?P<var>\w+)(?:\[(?P<idx>\d+)\])?\s*(?:(?P<op>==|!=|<=|>=|<|>)\s*(?P<val>\"[^\"]*\"|[-\w.]+))?)\s*")


def condition_matches(condition: str, machine: dict[str, Any]) -> bool:
    """Evaluate the `compatible_printers_condition` forms OrcaSlicer's bundled presets use (Prusa, CORE One):
    terms `var=~/re/`, `var!~/re/`, `var[i]==value` (also != < > <= >=) and bare booleans, joined by and/or.
    Anything else counts as not compatible (never offer a preset we can't check)."""
    def value(var: str, idx: str | None) -> Any:
        v = machine.get(var)
        if isinstance(v, list):
            v = v[int(idx or 0)] if len(v) > int(idx or 0) else None
        return v

    def term(t: str) -> bool:
        m = _TERM.fullmatch(t)
        if not m:
            raise ValueError(t)
        if m["re"]:
            hit = re.fullmatch(m["rx"], str(machine.get(m["re"]) or ""), re.S) is not None
            return hit if m["rop"] == "=~" else not hit
        v = value(m["var"], m["idx"])
        if not m["op"]:
            return str(v).lower() in ("1", "true")
        want = m["val"].strip('"')
        try:
            a, b = float(v), float(want)
        except (TypeError, ValueError):
            a, b = str(v), want
        return {"==": a == b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[m["op"]]

    try:
        # regexes may contain spaces/"and" - split only outside /.../
        parts = re.split(r"(\s+(?:and|or)\s+)(?=(?:[^/]*/[^/]*/)*[^/]*$)", condition.strip())
        result, joiner = term(parts[0]), None
        for piece in parts[1:]:
            if piece.strip() in ("and", "or"):
                joiner = piece.strip()
                continue
            # Orca: "and" binds tighter than "or"; conditions in the bundle use one kind only
            result = (result and term(piece)) if joiner == "and" else (result or term(piece))
        return bool(result)
    except (ValueError, IndexError, re.error):
        return False


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


    def machines(self) -> list[dict[str, str]]:
        """Selectable printer presets with their vendor folder, e.g. {"name": "Prusa MK4S 0.4 nozzle", "vendor": "Prusa"}."""
        with self._lock:
            if not hasattr(self, "_machines"):
                out = []
                for name, path in self._index["machine"].items():
                    data = self._load(path)
                    # abstract base presets and the vendor's model descriptions ("machine_model") can't slice
                    if data.get("instantiation") == "false" or data.get("type") == "machine_model":
                        continue
                    out.append({"name": name, "vendor": path.relative_to(self.profiles_dir).parts[0]})
                self._machines = sorted(out, key=lambda m: (m["vendor"].lower(), m["name"].lower()))
            return list(self._machines)

    LIBRARY_VENDOR = "OrcaFilamentLibrary"      # brand/generic materials for every printer ("Generic PLA @System")

    def compatible(self, kind: str, machine: str) -> list[str]:
        """User-selectable presets of `kind` for `machine`: the ones listing it in compatible_printers (or whose
        compatible_printers_condition matches it) first, then
        OrcaSlicer's printer-independent material library (no printer list, no condition), as the Orca GUI does."""
        key = (kind, machine)
        with self._lock:
            if key not in self._compatible:
                found, library = [], []
                try:
                    machine_preset = self.resolve("machine", machine)
                except ProfileError:
                    machine_preset = {}
                for name, path in self._index[kind].items():
                    if self._load(path).get("instantiation") == "false":
                        continue  # abstract base preset
                    try:
                        preset = self.resolve(kind, name)
                    except ProfileError:
                        continue
                    cp = preset.get("compatible_printers")
                    cond = preset.get("compatible_printers_condition")
                    if isinstance(cp, list) and machine in cp:
                        found.append(name)
                    elif not cp and cond and machine_preset and condition_matches(cond, machine_preset):
                        found.append(name)  # Prusa / CORE One presets select their printers by condition
                    elif (not cp and not preset.get("compatible_printers_condition")
                          and path.relative_to(self.profiles_dir).parts[0] == self.LIBRARY_VENDOR):
                        library.append(name)
                self._compatible[key] = sorted(found) + sorted(library, key=str.lower)
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
