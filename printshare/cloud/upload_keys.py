"""Keys for "send from OrcaSlicer" (docs/WEB.md step 3): one key per printer of an account.

OrcaSlicer's physical printer "Octo/Klipper" talks to https://api.pocketprint3d.com/octoprint with `X-Api-Key: <key>`;
the key says which account and which printer the upload is for. Keys are stored as SHA-256 only and shown once.
"""
from __future__ import annotations

import secrets
import time
from typing import Any

from .accounts import Accounts, _hash

KEY_PREFIX = "pp3do_"

SCHEMA = """
CREATE TABLE IF NOT EXISTS upload_keys (
  key_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, printer_id TEXT NOT NULL,
  created REAL NOT NULL, last_used REAL);
CREATE UNIQUE INDEX IF NOT EXISTS upload_keys_printer ON upload_keys(user_id, printer_id);
"""


class UploadKeys:
    def __init__(self, accounts: Accounts) -> None:
        self.acc = accounts
        with accounts.lock:
            accounts.db.executescript(SCHEMA)

    def create(self, user_id: str, printer_id: str, now: float | None = None) -> str:
        """A new key for this printer; an older one stops working."""
        key = KEY_PREFIX + secrets.token_urlsafe(24)
        with self.acc.lock:
            self.acc.db.execute("DELETE FROM upload_keys WHERE user_id = ? AND printer_id = ?", (user_id, printer_id))
            self.acc.db.execute("INSERT INTO upload_keys (key_hash, user_id, printer_id, created) VALUES (?, ?, ?, ?)",
                                (_hash(key), user_id, printer_id, now or time.time()))
        return key

    def info(self, user_id: str, printer_id: str) -> dict[str, Any] | None:
        rows = self.acc._q("SELECT created, last_used FROM upload_keys WHERE user_id = ? AND printer_id = ?",
                           (user_id, printer_id))
        return {"created": rows[0]["created"], "last_used": rows[0]["last_used"]} if rows else None

    def delete(self, user_id: str, printer_id: str) -> bool:
        with self.acc.lock:
            return self.acc.db.execute("DELETE FROM upload_keys WHERE user_id = ? AND printer_id = ?",
                                       (user_id, printer_id)).rowcount > 0

    def resolve(self, key: str, now: float | None = None) -> tuple[str, str] | None:
        """(user id, printer id) of a key, or None."""
        if not (key or "").startswith(KEY_PREFIX):
            return None
        rows = self.acc._q("SELECT user_id, printer_id, last_used FROM upload_keys WHERE key_hash = ?", (_hash(key),))
        if not rows:
            return None
        now = now or time.time()
        if not rows[0]["last_used"] or now - rows[0]["last_used"] > 60:
            self.acc._q("UPDATE upload_keys SET last_used = ? WHERE key_hash = ?", (now, _hash(key)))
        return rows[0]["user_id"], rows[0]["printer_id"]
