"""Bridges of cloud accounts (docs/BRIDGE.md): pairing by code, bridge tokens.

A bridge is the PocketPrint3D server in bridge mode at somebody's home. It pairs like this:
  1. bridge → `start_pairing(bridge_id, public_key)` → an 8-character code (shown at home) + a poll secret
  2. user in the app → `confirm_pairing(user, code)` → the bridge belongs to the account, a bridge token is made
  3. bridge → `poll_pairing(bridge_id, poll)` → gets the token once (it then lives only on the bridge)
Codes, poll secrets and tokens are stored as SHA-256 hashes, except the fresh token between steps 2 and 3 (at most
the code's lifetime; deleted when the bridge fetched it).
"""
from __future__ import annotations

import base64
import re
import secrets
import time
from typing import Any

from .accounts import AccountError, Accounts, _hash

PAIR_TTL_S = 10 * 60
PAIR_STARTS_PER_IP = 20          # per hour
PAIR_FAILS_PER_USER = 5          # wrong codes per 15 minutes
MAX_BRIDGES = 10                 # per account
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I
TOKEN_PREFIX = "pp3db_"
ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bridges (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL,
  token_hash TEXT UNIQUE NOT NULL, public_key TEXT, version TEXT, created REAL NOT NULL, last_seen REAL);
CREATE TABLE IF NOT EXISTS bridge_pairings (
  bridge_id TEXT PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL, poll_hash TEXT NOT NULL, public_key TEXT,
  version TEXT, name TEXT, ip TEXT, expires REAL NOT NULL, created REAL NOT NULL,
  user_id TEXT REFERENCES users(id) ON DELETE CASCADE, token TEXT);
CREATE TABLE IF NOT EXISTS bridge_pair_fails (user_id TEXT NOT NULL, created REAL NOT NULL);
"""


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _check_key(public_key: str | None) -> str | None:
    """X25519 public key, base64 (32 bytes) - used by the apps to seal printer secrets for this bridge."""
    if not public_key:
        return None
    try:
        if len(base64.b64decode(public_key, validate=True)) == 32:
            return public_key
    except ValueError:
        pass
    raise AccountError("public_key must be 32 bytes, base64")


class Bridges:
    def __init__(self, accounts: Accounts) -> None:
        self.acc = accounts
        with accounts.lock:
            accounts.db.executescript(SCHEMA)

    # ---------- pairing ----------
    def start_pairing(self, bridge_id: str, public_key: str | None = None, version: str | None = None,
                      name: str | None = None, ip: str | None = None, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        if not ID_RE.match(bridge_id or ""):
            raise AccountError("bridge_id: 8-64 letters, digits or dashes")
        key = _check_key(public_key)
        db = self.acc.db
        with self.acc.lock:
            db.execute("DELETE FROM bridge_pairings WHERE expires < ?", (now - 3600,))
            if ip and db.execute("SELECT COUNT(*) FROM bridge_pairings WHERE ip = ? AND created > ?",
                                 (ip, now - 3600)).fetchone()[0] >= PAIR_STARTS_PER_IP:
                raise AccountError("too many pairing attempts from this network - please try again later", 429)
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            poll = secrets.token_urlsafe(24)
            db.execute("DELETE FROM bridge_pairings WHERE bridge_id = ?", (bridge_id,))
            db.execute("INSERT INTO bridge_pairings (bridge_id, code_hash, poll_hash, public_key, version, name, ip, "
                       "expires, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (bridge_id, _hash(code), _hash(poll), key, (version or "")[:40] or None,
                        (name or "")[:60] or None, ip, now + PAIR_TTL_S, now))
        return {"code": format_code(code), "poll": poll, "expires_in": PAIR_TTL_S}

    def confirm_pairing(self, user_id: str, code: str, name: str | None = None,
                        now: float | None = None) -> dict[str, Any]:
        """The user entered the code in the app: the bridge now belongs to this account."""
        now = now or time.time()
        code = normalize_code(code)
        db = self.acc.db
        with self.acc.lock:
            db.execute("DELETE FROM bridge_pair_fails WHERE created < ?", (now - 900,))
            if db.execute("SELECT COUNT(*) FROM bridge_pair_fails WHERE user_id = ?",
                          (user_id,)).fetchone()[0] >= PAIR_FAILS_PER_USER:
                raise AccountError("too many wrong codes - please wait a few minutes", 429)
            row = db.execute("SELECT * FROM bridge_pairings WHERE code_hash = ? AND expires > ? AND user_id IS NULL",
                             (_hash(code), now)).fetchone() if len(code) == 8 else None
            if row is None:
                db.execute("INSERT INTO bridge_pair_fails (user_id, created) VALUES (?, ?)", (user_id, now))
                raise AccountError("unknown or expired code - the bridge shows a new one after 10 minutes", 404)
            existing = db.execute("SELECT user_id FROM bridges WHERE id = ?", (row["bridge_id"],)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM bridges WHERE user_id = ?", (user_id,)).fetchone()[0]
            if (existing is None or existing["user_id"] != user_id) and count >= MAX_BRIDGES:
                raise AccountError(f"at most {MAX_BRIDGES} bridges per account", 409)
            token = TOKEN_PREFIX + secrets.token_urlsafe(32)
            label = (name or row["name"] or "PocketPrint3D Bridge").strip()[:60]
            # pairing again (new owner, or the bridge lost its token): the old token stops working
            db.execute("DELETE FROM bridges WHERE id = ?", (row["bridge_id"],))
            db.execute("INSERT INTO bridges (id, user_id, name, token_hash, public_key, version, created) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (row["bridge_id"], user_id, label, _hash(token), row["public_key"], row["version"], now))
            db.execute("UPDATE bridge_pairings SET user_id = ?, token = ? WHERE bridge_id = ?",
                       (user_id, token, row["bridge_id"]))
        return self.get(user_id, row["bridge_id"])

    def poll_pairing(self, bridge_id: str, poll: str, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        db = self.acc.db
        with self.acc.lock:
            row = db.execute("SELECT * FROM bridge_pairings WHERE bridge_id = ?", (bridge_id,)).fetchone()
            if row is None or not secrets.compare_digest(row["poll_hash"], _hash(poll or "")):
                raise AccountError("unknown pairing - start again", 404)
            if row["token"]:
                db.execute("DELETE FROM bridge_pairings WHERE bridge_id = ?", (bridge_id,))
                email = db.execute("SELECT email FROM users WHERE id = ?", (row["user_id"],)).fetchone()
                return {"status": "paired", "token": row["token"], "account": email["email"] if email else None}
            if row["expires"] < now:
                db.execute("DELETE FROM bridge_pairings WHERE bridge_id = ?", (bridge_id,))
                raise AccountError("the code has expired - start again", 410)
        return {"status": "waiting", "expires_in": int(row["expires"] - now)}

    # ---------- bridges of an account ----------
    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"], "version": row["version"], "public_key": row["public_key"],
                "created": row["created"], "last_seen": row["last_seen"]}

    def list(self, user_id: str) -> list[dict[str, Any]]:
        return [self._public(r) for r in
                self.acc._q("SELECT * FROM bridges WHERE user_id = ? ORDER BY created", (user_id,))]

    def get(self, user_id: str, bridge_id: str) -> dict[str, Any]:
        rows = self.acc._q("SELECT * FROM bridges WHERE user_id = ? AND id = ?", (user_id, bridge_id))
        if not rows:
            raise AccountError("unknown bridge", 404)
        return self._public(rows[0])

    def rename(self, user_id: str, bridge_id: str, name: str) -> dict[str, Any]:
        name = (name or "").strip()[:60]
        if not name:
            raise AccountError("name must not be empty")
        self.get(user_id, bridge_id)
        self.acc._q("UPDATE bridges SET name = ? WHERE id = ?", (name, bridge_id))
        return self.get(user_id, bridge_id)

    def delete(self, user_id: str, bridge_id: str) -> bool:
        with self.acc.lock:
            return self.acc.db.execute("DELETE FROM bridges WHERE user_id = ? AND id = ?",
                                       (user_id, bridge_id)).rowcount > 0

    # ---------- the bridge itself ----------
    def for_token(self, token: str) -> dict[str, Any] | None:
        """{"id", "user_id", "name", …} of the bridge with this token, or None."""
        if not (token or "").startswith(TOKEN_PREFIX):
            return None
        rows = self.acc._q("SELECT * FROM bridges WHERE token_hash = ?", (_hash(token),))
        return {**self._public(rows[0]), "user_id": rows[0]["user_id"]} if rows else None

    def seen(self, bridge_id: str, version: str | None = None, now: float | None = None) -> None:
        self.acc._q("UPDATE bridges SET last_seen = ?, version = COALESCE(?, version) WHERE id = ?",
                    (now or time.time(), (version or "")[:40] or None, bridge_id))

    def count(self) -> int:
        return self.acc._q("SELECT COUNT(*) FROM bridges")[0][0]
