"""Filament presets from SpoolmanDB (https://github.com/Donkie/SpoolmanDB, MIT licence, Donkie and contributors) for
adding spools: brand → filament fills in name, material, colour, weight, spool weight, density.

The compiled database (`filaments.json`, ~4.6 MB, one entry per weight/diameter/colour combination) is fetched at most
once a day, kept in memory and on disk (an older copy is used when GitHub Pages can't be reached) and condensed to one
entry per brand + name + material + colour.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .fetch import UA

URL = "https://donkie.github.io/SpoolmanDB/filaments.json"
TTL_S = 24 * 3600
MAX_BYTES = 30 * 1024 * 1024


class FilamentDbError(Exception):
    pass


class FilamentDb:
    def __init__(self, cache_dir: str | Path, http: httpx.Client | None = None) -> None:
        self.cache = Path(cache_dir) / "spoolmandb-filaments.json"
        self.http = http
        self.lock = threading.Lock()
        self.loaded = 0.0
        self.brands: dict[str, list[dict[str, Any]]] = {}

    # ---------- loading ----------
    def _download(self) -> bytes:
        client = self.http or httpx.Client(timeout=60, headers={"User-Agent": UA}, follow_redirects=True)
        try:
            r = client.get(URL)
            if r.status_code != 200:
                raise FilamentDbError(f"SpoolmanDB answered HTTP {r.status_code}")
            if len(r.content) > MAX_BYTES:
                raise FilamentDbError("SpoolmanDB file too large")
            return r.content
        except httpx.HTTPError as e:
            raise FilamentDbError(f"SpoolmanDB not reachable ({e.__class__.__name__})") from e
        finally:
            if self.http is None:
                client.close()

    def _ensure(self) -> None:
        with self.lock:
            if self.brands and time.time() - self.loaded < TTL_S:
                return
            raw = None
            fresh = self.cache.is_file() and time.time() - self.cache.stat().st_mtime < TTL_S
            if not fresh:
                try:
                    raw = self._download()
                    self.cache.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self.cache.with_suffix(".tmp")
                    tmp.write_bytes(raw)
                    tmp.replace(self.cache)
                except (FilamentDbError, OSError):
                    raw = None        # use the older copy if there is one
            if raw is None:
                if not self.cache.is_file():
                    if self.brands:
                        return
                    raise FilamentDbError("the filament database is not available right now")
                raw = self.cache.read_bytes()
            try:
                self.brands = condense(json.loads(raw))
            except (ValueError, TypeError, KeyError) as e:
                raise FilamentDbError("the filament database could not be read") from e
            self.loaded = time.time()

    # ---------- queries ----------
    def brand_list(self) -> list[dict[str, Any]]:
        self._ensure()
        return [{"name": b, "count": len(items)} for b, items in sorted(self.brands.items(), key=lambda x: x[0].lower())]

    def filaments(self, brand: str, diameter: float = 1.75) -> list[dict[str, Any]]:
        self._ensure()
        items = self.brands.get(brand)
        if items is None:
            raise FilamentDbError(f"unknown brand {brand!r}")
        return [{k: v for k, v in f.items() if k != "diameters"} | {"diameter": diameter}
                for f in items if diameter in f["diameters"]]


def condense(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """One entry per brand + name + material + colour: weights (net filament, with their empty spool weight) and
    diameters collected."""
    out: dict[str, dict[tuple, dict[str, Any]]] = {}
    for e in entries:
        if not isinstance(e, dict) or not e.get("manufacturer") or not e.get("material"):
            continue
        key = (e.get("name") or "", e["material"], e.get("color_hex") or "", ",".join(e.get("color_hexes") or []))
        brand = out.setdefault(str(e["manufacturer"]), {})
        f = brand.get(key)
        if f is None:
            f = brand[key] = {
                "id": e.get("id"), "name": e.get("name") or "", "material": e["material"],
                "color_hex": e.get("color_hex"), "color_hexes": e.get("color_hexes"),
                "density": e.get("density"), "extruder_temp": e.get("extruder_temp"), "bed_temp": e.get("bed_temp"),
                "finish": e.get("finish"), "translucent": bool(e.get("translucent")), "glow": bool(e.get("glow")),
                "weights": [], "diameters": [],
            }
        w = {"weight": e.get("weight"), "spool_weight": e.get("spool_weight")}
        if w["weight"] and w not in f["weights"]:
            f["weights"].append(w)
        if e.get("diameter") and e["diameter"] not in f["diameters"]:
            f["diameters"].append(e["diameter"])
    return {b: sorted(items.values(), key=lambda f: (f["material"].lower(), f["name"].lower()))
            for b, items in out.items()}
