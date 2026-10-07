"""Spools by NFC chip and spools per slot (0.38.0): shared by the app, the web app and NFC readers at the printer.

- `spool_tags`: chip number (UID of any NFC chip: OpenPrintTag, NTAG sticker, a Bambu spool's MIFARE tag) → spool. A
  chip is linked once ("which spool is this?"); a spool may have several chips (Bambu glues one on each side).
- `slot_spools`: which spool sits in which slot of a printer (tool number: AMS tray 0-15, Bambu external spool 254,
  AFC lane tool …). A spool is in one slot at a time. The print screen proposes and books the slot's spool.
- `reader_scans`: the last chip an NFC reader saw per slot - an unknown chip shows in the app as "link this chip".
- `reader_keys` (cloud): one key per printer for an NFC reader (ESP32 + PN5180), stored as SHA-256 only, shown once.

`owner` is the cloud user id, or "local" on a home server. One SQLite file: next to the cloud database, or in the home
server's config folder.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

KEY_PREFIX = "pp3dr_"
UID_RE = re.compile(r"^[0-9A-F]{8,32}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS spool_tags (
  owner TEXT NOT NULL, uid TEXT NOT NULL, spool INTEGER NOT NULL, created REAL NOT NULL, PRIMARY KEY (owner, uid));
CREATE TABLE IF NOT EXISTS slot_spools (
  owner TEXT NOT NULL, printer TEXT NOT NULL, tool INTEGER NOT NULL, spool INTEGER NOT NULL, source TEXT NOT NULL,
  updated REAL NOT NULL, PRIMARY KEY (owner, printer, tool));
CREATE TABLE IF NOT EXISTS reader_scans (
  owner TEXT NOT NULL, printer TEXT NOT NULL, tool INTEGER NOT NULL, uid TEXT NOT NULL, spool INTEGER, at REAL NOT NULL,
  PRIMARY KEY (owner, printer, tool));
CREATE TABLE IF NOT EXISTS reader_keys (
  key_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, printer TEXT NOT NULL, created REAL NOT NULL, last_used REAL);
CREATE UNIQUE INDEX IF NOT EXISTS reader_keys_printer ON reader_keys(owner, printer);
"""


class TagError(ValueError):
    pass


def normalize_uid(uid: str) -> str:
    """"04:a2:3b:…" / "04 A2 3B" / "04a23b…" → "04A23B…" (hex, 4-16 bytes)."""
    u = re.sub(r"[^0-9A-Fa-f]", "", str(uid or "")).upper()
    if not UID_RE.match(u):
        raise TagError("the chip number must be 4-16 bytes in hex, e.g. 04A23B1C5D6E80")
    return u


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class SpoolTags:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    # ---------- chip → spool ----------
    def link(self, owner: str, uid: str, spool: int, now: float | None = None) -> dict[str, Any]:
        uid = normalize_uid(uid)
        now = now or time.time()
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO spool_tags (owner, uid, spool, created) VALUES (?, ?, ?, ?)",
                            (owner, uid, int(spool), now))
            # a reader already saw this chip in a slot: the spool is in that slot now
            for r in self.db.execute("SELECT printer, tool FROM reader_scans WHERE owner = ? AND uid = ?",
                                     (owner, uid)).fetchall():
                self._set_slot(owner, r["printer"], r["tool"], int(spool), "reader", now)
                self.db.execute("UPDATE reader_scans SET spool = ? WHERE owner = ? AND printer = ? AND tool = ?",
                                (int(spool), owner, r["printer"], r["tool"]))
        return {"uid": uid, "spool": int(spool)}

    def unlink(self, owner: str, uid: str) -> bool:
        with self.lock:
            return self.db.execute("DELETE FROM spool_tags WHERE owner = ? AND uid = ?",
                                   (owner, normalize_uid(uid))).rowcount > 0

    def spool_for(self, owner: str, uid: str) -> int | None:
        rows = self._q("SELECT spool FROM spool_tags WHERE owner = ? AND uid = ?", (owner, normalize_uid(uid)))
        return rows[0]["spool"] if rows else None

    def links(self, owner: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT uid, spool, created FROM spool_tags WHERE owner = ? ORDER BY created",
                                         (owner,))]

    # ---------- slot → spool ----------
    def _set_slot(self, owner: str, printer: str, tool: int, spool: int | None, source: str, now: float) -> None:
        if spool is None:
            self.db.execute("DELETE FROM slot_spools WHERE owner = ? AND printer = ? AND tool = ?", (owner, printer, tool))
            return
        # a spool sits in one slot at a time - moving it clears the old slot (on any printer)
        self.db.execute("DELETE FROM slot_spools WHERE owner = ? AND spool = ?", (owner, spool))
        self.db.execute("INSERT OR REPLACE INTO slot_spools (owner, printer, tool, spool, source, updated) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (owner, printer, tool, spool, source, now))

    def set_slot(self, owner: str, printer: str, tool: int, spool: int | None, source: str = "app",
                 now: float | None = None) -> None:
        with self.lock:
            self._set_slot(owner, printer, int(tool), None if spool is None else int(spool), source, now or time.time())

    def slots(self, owner: str, printer: str) -> dict[str, dict[str, Any]]:
        return {str(r["tool"]): {"spool": r["spool"], "source": r["source"], "updated": r["updated"]}
                for r in self._q("SELECT tool, spool, source, updated FROM slot_spools WHERE owner = ? AND printer = ?",
                                 (owner, printer))}

    def forget_printer(self, owner: str, printer: str) -> None:
        with self.lock:
            for table in ("slot_spools", "reader_scans", "reader_keys"):
                self.db.execute(f"DELETE FROM {table} WHERE owner = ? AND printer = ?", (owner, printer))

    def forget_owner(self, owner: str) -> None:
        with self.lock:
            for table in ("spool_tags", "slot_spools", "reader_scans", "reader_keys"):
                self.db.execute(f"DELETE FROM {table} WHERE owner = ?", (owner,))

    # ---------- NFC reader at the printer ----------
    def scan(self, owner: str, printer: str, tool: int, uid: str, now: float | None = None) -> int | None:
        """A reader saw `uid` in this slot: the linked spool now sits there (None = unknown chip, the app asks)."""
        uid = normalize_uid(uid)
        now = now or time.time()
        with self.lock:
            rows = self.db.execute("SELECT spool FROM spool_tags WHERE owner = ? AND uid = ?", (owner, uid)).fetchall()
            spool = rows[0]["spool"] if rows else None
            self.db.execute("INSERT OR REPLACE INTO reader_scans (owner, printer, tool, uid, spool, at) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (owner, printer, int(tool), uid, spool, now))
            if spool is not None:
                self._set_slot(owner, printer, int(tool), spool, "reader", now)
        return spool

    def scans(self, owner: str, printer: str) -> dict[str, dict[str, Any]]:
        return {str(r["tool"]): {"uid": r["uid"], "spool": r["spool"], "at": r["at"]}
                for r in self._q("SELECT tool, uid, spool, at FROM reader_scans WHERE owner = ? AND printer = ?",
                                 (owner, printer))}

    def create_key(self, owner: str, printer: str, now: float | None = None) -> str:
        key = KEY_PREFIX + secrets.token_urlsafe(24)
        with self.lock:
            self.db.execute("DELETE FROM reader_keys WHERE owner = ? AND printer = ?", (owner, printer))
            self.db.execute("INSERT INTO reader_keys (key_hash, owner, printer, created) VALUES (?, ?, ?, ?)",
                            (_hash(key), owner, printer, now or time.time()))
        return key

    def key_info(self, owner: str, printer: str) -> dict[str, Any] | None:
        rows = self._q("SELECT created, last_used FROM reader_keys WHERE owner = ? AND printer = ?", (owner, printer))
        return {"created": rows[0]["created"], "last_used": rows[0]["last_used"]} if rows else None

    def delete_key(self, owner: str, printer: str) -> bool:
        with self.lock:
            return self.db.execute("DELETE FROM reader_keys WHERE owner = ? AND printer = ?",
                                   (owner, printer)).rowcount > 0

    def resolve_key(self, key: str, now: float | None = None) -> tuple[str, str] | None:
        """(owner, printer) of a reader key, or None."""
        if not (key or "").startswith(KEY_PREFIX):
            return None
        rows = self._q("SELECT owner, printer, last_used FROM reader_keys WHERE key_hash = ?", (_hash(key),))
        if not rows:
            return None
        now = now or time.time()
        if not rows[0]["last_used"] or now - rows[0]["last_used"] > 60:
            self._q("UPDATE reader_keys SET last_used = ? WHERE key_hash = ?", (now, _hash(key)))
        return rows[0]["owner"], rows[0]["printer"]
