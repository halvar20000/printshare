"""Spools per cloud account: a small Spoolman for users without a server at home (docs/API.md "Spoolman").

The API answers in Spoolman's shapes (https://donkie.github.io/Spoolman/), so the apps use the same code for a real
Spoolman and for this one. Spool ids are numbered per account (#1, #2 …). Filament and vendor live inside the spool
(Spoolman keeps them in their own tables; creating a spool is therefore PocketPrint3D's own, simpler request).
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from typing import Any

from .accounts import AccountError, Accounts

MAX_SPOOLS = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS spools (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, num INTEGER NOT NULL,
  registered REAL NOT NULL, first_used REAL, last_used REAL, used_weight REAL NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL, PRIMARY KEY (user_id, num));
"""

# fields kept in `data` (everything the user enters)
FILAMENT_KEYS = ("name", "vendor", "material", "color_hex", "density", "diameter", "weight")
SPOOL_KEYS = ("initial_weight", "spool_weight", "location", "comment")


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


def _length(grams: float | None, f: dict[str, Any]) -> float | None:
    """Filament length in mm for a weight: g / (g/cm³) = cm³ = 1000 mm³, divided by the cross-section in mm²."""
    if grams is None:
        return None
    r = (f.get("diameter") or 1.75) / 2
    return round(grams / (f.get("density") or 1.24) * 1000 / (math.pi * r * r), 1)


class Spools:
    def __init__(self, accounts: Accounts) -> None:
        self.acc = accounts
        with accounts.lock:
            accounts.db.executescript(SCHEMA)

    # ---------- shape ----------
    @staticmethod
    def _json(row: Any) -> dict[str, Any]:
        d = json.loads(row["data"])
        f = d.get("filament") or {}
        initial = d.get("initial_weight") or f.get("weight")
        used = row["used_weight"]
        remaining = max(0.0, initial - used) if initial else None
        reg = _iso(row["registered"])
        color = (f.get("color_hex") or "").lstrip("#").upper() or None
        return {
            "id": row["num"], "registered": reg, "first_used": _iso(row["first_used"]),
            "last_used": _iso(row["last_used"]),
            "filament": {"id": row["num"], "registered": reg, "name": f.get("name"),
                         "vendor": {"id": row["num"], "registered": reg, "name": f["vendor"], "extra": {}}
                         if f.get("vendor") else None,
                         "material": f.get("material"), "density": f.get("density") or 1.24,
                         "diameter": f.get("diameter") or 1.75, "weight": f.get("weight"),
                         "color_hex": color, "extra": {}},
            "initial_weight": d.get("initial_weight"), "spool_weight": d.get("spool_weight"),
            "used_weight": round(used, 2), "remaining_weight": round(remaining, 2) if remaining is not None else None,
            "used_length": _length(used, f), "remaining_length": _length(remaining, f),
            "location": d.get("location"), "comment": d.get("comment"), "archived": bool(row["archived"]),
            "extra": {},
        }

    def _row(self, user_id: str, num: int) -> Any:
        rows = self.acc._q("SELECT * FROM spools WHERE user_id = ? AND num = ?", (user_id, num))
        if not rows:
            raise AccountError(f"spool #{num} not found", 404)
        return rows[0]

    # ---------- read ----------
    def list(self, user_id: str, allow_archived: bool = False) -> list[dict[str, Any]]:
        rows = self.acc._q(
            "SELECT * FROM spools WHERE user_id = ?" + ("" if allow_archived else " AND archived = 0")
            + " ORDER BY last_used IS NULL, last_used DESC, num", (user_id,))
        return [self._json(r) for r in rows]

    def get(self, user_id: str, num: int) -> dict[str, Any]:
        return self._json(self._row(user_id, num))

    # ---------- write ----------
    @staticmethod
    def _merge(data: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        out = {k: data.get(k) for k in SPOOL_KEYS}
        out["filament"] = dict(data.get("filament") or {})
        out.update({k: changes[k] for k in SPOOL_KEYS if k in changes})
        if "filament" in changes and changes["filament"] is not None:
            out["filament"].update({k: v for k, v in changes["filament"].items() if k in FILAMENT_KEYS})
        return out

    @staticmethod
    def _used_for(data: dict[str, Any], remaining: float) -> tuple[dict[str, Any], float]:
        """`remaining_weight` given by the user: used = initial - remaining (initial = remaining if unknown)."""
        initial = data.get("initial_weight") or (data.get("filament") or {}).get("weight")
        if not initial:
            data["initial_weight"] = initial = remaining
        return data, max(0.0, initial - remaining)

    def create(self, user_id: str, spool: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        data = self._merge({}, spool)
        used = 0.0
        if spool.get("remaining_weight") is not None:
            data, used = self._used_for(data, spool["remaining_weight"])
        with self.acc.lock:
            count, top = self.acc.db.execute("SELECT COUNT(*), COALESCE(MAX(num), 0) FROM spools WHERE user_id = ?",
                                             (user_id,)).fetchone()
            if count >= MAX_SPOOLS:
                raise AccountError(f"at most {MAX_SPOOLS} spools per account - archive or delete old ones", 400)
            self.acc.db.execute("INSERT INTO spools (user_id, num, registered, used_weight, archived, data) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (user_id, top + 1, now, used, int(bool(spool.get("archived"))), json.dumps(data)))
        return self.get(user_id, top + 1)

    def update(self, user_id: str, num: int, changes: dict[str, Any]) -> dict[str, Any]:
        row = self._row(user_id, num)
        data = self._merge(json.loads(row["data"]), changes)
        used = row["used_weight"]
        if changes.get("remaining_weight") is not None:
            data, used = self._used_for(data, changes["remaining_weight"])
        archived = int(bool(changes["archived"])) if changes.get("archived") is not None else row["archived"]
        self.acc._q("UPDATE spools SET data = ?, used_weight = ?, archived = ? WHERE user_id = ? AND num = ?",
                    (json.dumps(data), used, archived, user_id, num))
        return self.get(user_id, num)

    def delete(self, user_id: str, num: int) -> None:
        self._row(user_id, num)
        self.acc._q("DELETE FROM spools WHERE user_id = ? AND num = ?", (user_id, num))

    def use(self, user_id: str, num: int, weight: float | None = None, length: float | None = None,
            now: float | None = None) -> dict[str, Any]:
        """Book used filament like Spoolman's PUT /spool/{id}/use: either a weight (g) or a length (mm)."""
        if (weight is None) == (length is None):
            raise AccountError("give either use_weight or use_length", 400)
        row = self._row(user_id, num)
        if weight is None:
            f = json.loads(row["data"]).get("filament") or {}
            r = (f.get("diameter") or 1.75) / 2
            weight = length * math.pi * r * r / 1000 * (f.get("density") or 1.24)
        now = now or time.time()
        self.acc._q("UPDATE spools SET used_weight = MAX(0, used_weight + ?), last_used = ?, "
                    "first_used = COALESCE(first_used, ?) WHERE user_id = ? AND num = ?",
                    (weight, now, now, user_id, num))
        return self.get(user_id, num)

    def count(self) -> int:
        return self.acc._q("SELECT COUNT(*) FROM spools")[0][0]
