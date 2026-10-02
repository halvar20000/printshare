"""Accounts for the hosted service (cloud mode, docs/CLOUD.md): e-mail login codes, sessions, printers, usage.

SQLite (stdlib) in the data volume - one server is enough for the start. Codes and session tokens are only
stored as SHA-256 hashes; a stolen database can't be used to log in.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CODE_TTL_S = 10 * 60          # a login code is valid for 10 minutes
CODE_ATTEMPTS = 5             # wrong entries per code
CODES_PER_EMAIL = 3           # per 15 minutes
CODES_PER_IP = 10             # per hour
SESSION_PREFIX = "pp3d_"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, created REAL NOT NULL, last_login REAL);
CREATE TABLE IF NOT EXISTS login_codes (
  email TEXT NOT NULL, code_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  ip TEXT, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS login_codes_email ON login_codes(email);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device TEXT, created REAL NOT NULL, last_used REAL NOT NULL);
CREATE TABLE IF NOT EXISTS printers (
  id TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  config TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY (user_id, id));
CREATE TABLE IF NOT EXISTS usage (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, day TEXT NOT NULL, slices INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day));
"""


class AccountError(Exception):
    """Shown to the user; `status` is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class User:
    id: str
    email: str


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not EMAIL_RE.match(e) or len(e) > 254:
        raise AccountError("please enter a valid e-mail address")
    return e


class Accounts:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    # ---------- login ----------
    def request_code(self, email: str, ip: str | None = None, now: float | None = None) -> str:
        """New 6-digit code for `email` (the caller mails it). Rate limited per address and per IP."""
        now = now or time.time()
        email = normalize_email(email)
        with self.lock:
            self.db.execute("DELETE FROM login_codes WHERE created < ?", (now - 3600,))
            recent = self.db.execute("SELECT COUNT(*) FROM login_codes WHERE email = ? AND created > ?",
                                     (email, now - 900)).fetchone()[0]
            if recent >= CODES_PER_EMAIL:
                raise AccountError("too many codes requested - please wait a few minutes", 429)
            if ip and self.db.execute("SELECT COUNT(*) FROM login_codes WHERE ip = ? AND created > ?",
                                      (ip, now - 3600)).fetchone()[0] >= CODES_PER_IP:
                raise AccountError("too many codes requested from this network - please try again later", 429)
            code = f"{secrets.randbelow(1_000_000):06d}"
            self.db.execute("INSERT INTO login_codes (email, code_hash, expires, ip, created) VALUES (?, ?, ?, ?, ?)",
                            (email, _hash(f"{email}:{code}"), now + CODE_TTL_S, ip, now))
        return code

    def verify_code(self, email: str, code: str, device: str | None = None,
                    now: float | None = None) -> tuple[User, str]:
        """Check a code; creates the account on first login. Returns the user and a new session token."""
        now = now or time.time()
        email = normalize_email(email)
        code = re.sub(r"\D", "", code or "")
        with self.lock:
            rows = self.db.execute("SELECT rowid, code_hash, expires, attempts FROM login_codes WHERE email = ? "
                                   "ORDER BY created DESC", (email,)).fetchall()
            valid = [r for r in rows if r["expires"] > now and r["attempts"] < CODE_ATTEMPTS]
            if not valid:
                raise AccountError("the code has expired - please request a new one", 401)
            match = next((r for r in valid if secrets.compare_digest(r["code_hash"], _hash(f"{email}:{code}"))), None)
            if match is None:
                self.db.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE email = ?", (email,))
                raise AccountError("wrong code", 401)
            self.db.execute("DELETE FROM login_codes WHERE email = ?", (email,))    # a code works once
            row = self.db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            uid = row["id"] if row else uuid.uuid4().hex[:16]
            if not row:
                self.db.execute("INSERT INTO users (id, email, created) VALUES (?, ?, ?)", (uid, email, now))
            self.db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, uid))
            token = SESSION_PREFIX + secrets.token_urlsafe(32)
            self.db.execute("INSERT INTO sessions (token_hash, user_id, device, created, last_used) VALUES (?, ?, ?, ?, ?)",
                            (_hash(token), uid, (device or "")[:80] or None, now, now))
        return User(uid, email), token

    # ---------- sessions ----------
    def user_for_token(self, token: str, now: float | None = None) -> User | None:
        if not token.startswith(SESSION_PREFIX):
            return None
        now = now or time.time()
        with self.lock:
            row = self.db.execute("SELECT u.id, u.email, s.last_used FROM sessions s JOIN users u ON u.id = s.user_id "
                                  "WHERE s.token_hash = ?", (_hash(token),)).fetchone()
            if row is None:
                return None
            if now - row["last_used"] > 300:          # don't write on every request
                self.db.execute("UPDATE sessions SET last_used = ? WHERE token_hash = ?", (now, _hash(token)))
        return User(row["id"], row["email"])

    def user(self, user_id: str) -> User | None:
        rows = self._q("SELECT id, email FROM users WHERE id = ?", (user_id,))
        return User(rows[0]["id"], rows[0]["email"]) if rows else None

    def logout(self, token: str) -> None:
        self._q("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))

    def delete_user(self, user_id: str) -> None:
        """Everything of the account goes (sessions, printers, usage via ON DELETE CASCADE)."""
        with self.lock:
            email = self.db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if email:
                self.db.execute("DELETE FROM login_codes WHERE email = ?", (email["email"],))

    # ---------- printers (no addresses: the phone reaches them on the home network) ----------
    def printers(self, user_id: str) -> list[dict[str, Any]]:
        return [json.loads(r["config"]) for r in
                self._q("SELECT config FROM printers WHERE user_id = ? ORDER BY created", (user_id,))]

    def save_printer(self, user_id: str, config: dict[str, Any], now: float | None = None) -> None:
        with self.lock:
            exists = self.db.execute("SELECT 1 FROM printers WHERE user_id = ? AND id = ?",
                                     (user_id, config["id"])).fetchone()
            if exists:
                self.db.execute("UPDATE printers SET config = ? WHERE user_id = ? AND id = ?",
                                (json.dumps(config), user_id, config["id"]))
            else:
                self.db.execute("INSERT INTO printers (id, user_id, config, created) VALUES (?, ?, ?, ?)",
                                (config["id"], user_id, json.dumps(config), now or time.time()))

    def delete_printer(self, user_id: str, printer_id: str) -> bool:
        with self.lock:
            return self.db.execute("DELETE FROM printers WHERE user_id = ? AND id = ?",
                                   (user_id, printer_id)).rowcount > 0

    def delete_bridge_printers(self, bridge_id: str, keep_user: str | None = None) -> int:
        """Printers synced from a bridge (removed bridge, or the bridge moved to another account)."""
        with self.lock:
            return self.db.execute("DELETE FROM printers WHERE json_extract(config, '$.bridge') = ? AND user_id != ?",
                                   (bridge_id, keep_user or "")).rowcount

    # ---------- limits ----------
    def count_slice(self, user_id: str, limit: int, now: float | None = None) -> int:
        """Book one slice for today; AccountError 429 when the daily limit is reached."""
        day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
        with self.lock:
            row = self.db.execute("SELECT slices FROM usage WHERE user_id = ? AND day = ?", (user_id, day)).fetchone()
            used = row["slices"] if row else 0
            if used >= limit:
                raise AccountError(f"daily limit reached ({limit} slices per day) - please try again tomorrow", 429)
            self.db.execute("INSERT INTO usage (user_id, day, slices) VALUES (?, ?, 1) "
                            "ON CONFLICT(user_id, day) DO UPDATE SET slices = slices + 1", (user_id, day))
        return used + 1

    def usage_today(self, user_id: str, now: float | None = None) -> int:
        day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
        row = self._q("SELECT slices FROM usage WHERE user_id = ? AND day = ?", (user_id, day))
        return row[0]["slices"] if row else 0

    def stats(self) -> dict[str, int]:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        return {"users": self._q("SELECT COUNT(*) FROM users")[0][0],
                "sessions": self._q("SELECT COUNT(*) FROM sessions")[0][0],
                "printers": self._q("SELECT COUNT(*) FROM printers")[0][0],
                "slices_today": self._q("SELECT COALESCE(SUM(slices), 0) FROM usage WHERE day = ?", (day,))[0][0]}
