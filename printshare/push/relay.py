"""The push relay (cloud only): APNs tokens → opaque handles, messages from any PocketPrint3D server → APNs.

A phone registers each APNs token here (`register`): the device token for notifications, the push-to-start token for
Live Activities and every Live Activity's own update token. It gets a random `handle` + `secret` back and hands both to
its server (the cloud account, a home server, a bridge-less Home Assistant add-on …). The server sends messages with
them (`send`); only the relay knows the token and holds the .p8 key.

What the relay sees:
- notifications: an encrypted blob (ChaCha20-Poly1305, key from the phone, see notify.py) + category and urgency. The
  app's Notification Service Extension decrypts it; without it iOS shows the fallback text "push.fallback".
- Live Activity updates: their content state in plain text (Apple applies it without an extension), so it carries
  numbers only (state code, %, end time, layers) and ids, never names or file names.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .apns import APNs

KINDS = ("device", "start", "activity")
ENVS = ("production", "sandbox")
TOKEN_RE = re.compile(r"^[0-9a-f]{64,200}$")
HANDLE_RE = re.compile(r"^pp3dp_[A-Za-z0-9_-]{22,40}$")
MAX_BLOB = 3000                    # base64 of the encrypted notification (APNs payloads are at most 4 KB)
STATE_KEYS = {"s": str, "p": (int, float), "end": int, "l": int, "lt": int}
STATES = ("sending", "waking", "decision", "printing", "paused", "done", "cancelled", "error", "failed")
LEVELS = ("passive", "active", "time-sensitive")
# per handle and hour; Live Activities have Apple's own budget on top (priority 10 counts, 5 doesn't)
LIMITS = {"device": 60, "start": 20, "activity": 240}
REGISTER_PER_IP_HOUR = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_handles (
  handle TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, token TEXT NOT NULL, kind TEXT NOT NULL, env TEXT NOT NULL,
  platform TEXT NOT NULL, created REAL NOT NULL, last_used REAL, window_start REAL NOT NULL DEFAULT 0,
  window_count INTEGER NOT NULL DEFAULT 0, sent INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS push_handles_token ON push_handles(token, kind);
"""


class RelayError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status, self.code = status, code


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _id(text: Any, limit: int = 64) -> str | None:
    s = str(text or "")
    return s if re.fullmatch(r"[A-Za-z0-9_.:-]{1,%d}" % limit, s) else None


def activity_state(state: Any) -> dict[str, Any]:
    """Only the known keys with the right types: the content state goes to APNs in plain text."""
    if not isinstance(state, dict):
        raise RelayError(400, "invalid", "state must be an object")
    out: dict[str, Any] = {}
    for key, typ in STATE_KEYS.items():
        val = state.get(key)
        if val is None:
            continue
        if isinstance(val, bool) or not isinstance(val, typ):
            raise RelayError(400, "invalid", f"state.{key} has the wrong type")
        out[key] = val
    if out.get("s") not in STATES:
        raise RelayError(400, "invalid", "state.s is unknown")
    if isinstance(out.get("p"), (int, float)):
        out["p"] = max(0, min(100, round(float(out["p"]))))
    return out


def build(kind: str, msg: dict[str, Any], now: float | None = None) -> tuple[dict[str, Any], str, int, str | None]:
    """APNs payload, push type, priority and collapse id for a message; RelayError when it doesn't fit the handle."""
    now = now or time.time()
    typ = msg.get("type")
    if typ == "alert":
        if kind != "device":
            raise RelayError(400, "wrong_handle", "notifications go to a device handle")
        blob = msg.get("data")
        if not isinstance(blob, str) or not 16 <= len(blob) <= MAX_BLOB or not re.fullmatch(r"[A-Za-z0-9+/=]+", blob):
            raise RelayError(400, "invalid", "data must be the encrypted notification (base64)")
        level = msg.get("level") if msg.get("level") in LEVELS else "active"
        aps: dict[str, Any] = {"alert": {"loc-key": "push.fallback"}, "mutable-content": 1, "sound": "default",
                               "interruption-level": level}
        for key, apskey in (("category", "category"), ("thread", "thread-id")):
            val = _id(msg.get(key), 40)
            if val:
                aps[apskey] = val
        return {"aps": aps, "pp3d": blob}, "alert", 10, _id(msg.get("collapse"))
    if typ == "activity":
        event = msg.get("event")
        state = activity_state(msg.get("state"))
        aps = {"timestamp": int(now), "event": event, "content-state": state}
        if event == "start":
            if kind != "start":
                raise RelayError(400, "wrong_handle", "a Live Activity starts through the push-to-start handle")
            attrs = msg.get("attributes") if isinstance(msg.get("attributes"), dict) else {}
            job, printer = _id(attrs.get("job"), 40), _id(attrs.get("printer"), 64)
            if not job or not printer:
                raise RelayError(400, "invalid", "attributes need job and printer ids")
            aps.update({"attributes-type": "PrintActivityAttributes", "attributes": {"job": job, "printer": printer},
                        "alert": {"title": {"loc-key": "push.activity.title"},
                                  "body": {"loc-key": "push.activity.body"}}})
        elif event in ("update", "end"):
            if kind != "activity":
                raise RelayError(400, "wrong_handle", "updates go to the Live Activity's own handle")
        else:
            raise RelayError(400, "invalid", "event must be start, update or end")
        for key, apskey in (("stale", "stale-date"), ("dismiss", "dismissal-date")):
            if isinstance(msg.get(key), int) and not isinstance(msg.get(key), bool):
                aps[apskey] = msg[key]
        priority = 10 if msg.get("urgent") or event != "update" else 5
        return {"aps": aps}, "liveactivity", priority, None
    raise RelayError(400, "invalid", "type must be alert or activity")


class Relay:
    def __init__(self, path: str | Path, apns: APNs | None) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()
        self.apns = apns
        self._registrations: dict[str, list[float]] = {}

    @property
    def available(self) -> bool:
        return self.apns is not None

    def register(self, token: str, kind: str, env: str, platform: str = "ios", ip: str = "",
                 now: float | None = None) -> dict[str, str]:
        now = now or time.time()
        token = str(token or "").strip().lower()
        if not TOKEN_RE.match(token):
            raise RelayError(400, "invalid", "token must be the APNs token in hex")
        if kind not in KINDS or env not in ENVS or platform != "ios":
            raise RelayError(400, "invalid", "unknown kind, env or platform")
        recent = [t for t in self._registrations.get(ip, []) if now - t < 3600]
        if len(recent) >= REGISTER_PER_IP_HOUR:
            raise RelayError(429, "rate_limited", "too many registrations from this address")
        self._registrations[ip] = recent + [now]
        handle, secret = "pp3dp_" + secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        with self.lock:
            # the same token registered again (app reinstalled, new server): one handle per token and kind
            self.db.execute("DELETE FROM push_handles WHERE token = ? AND kind = ?", (token, kind))
            self.db.execute("INSERT INTO push_handles (handle, secret_hash, token, kind, env, platform, created) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)", (handle, _hash(secret), token, kind, env, platform, now))
        return {"handle": handle, "secret": secret}

    def _row(self, handle: str, secret: str) -> sqlite3.Row:
        if not HANDLE_RE.match(str(handle or "")):
            raise RelayError(404, "unknown_handle")
        with self.lock:
            row = self.db.execute("SELECT * FROM push_handles WHERE handle = ?", (handle,)).fetchone()
        if row is None or not hmac.compare_digest(row["secret_hash"], _hash(str(secret or ""))):
            raise RelayError(404, "unknown_handle")
        return row

    def remove(self, handle: str, secret: str) -> None:
        self._row(handle, secret)
        with self.lock:
            self.db.execute("DELETE FROM push_handles WHERE handle = ?", (handle,))

    async def send(self, handle: str, secret: str, msg: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        if self.apns is None:
            raise RelayError(503, "push_unavailable", "push notifications are not set up on this server")
        now = now or time.time()
        row = self._row(handle, secret)
        payload, push_type, priority, collapse = build(row["kind"], msg, now)
        if len(json.dumps(payload)) > 4096:
            raise RelayError(400, "too_large")
        start, count = row["window_start"], row["window_count"]
        if now - start >= 3600:
            start, count = now, 0
        if count >= LIMITS[row["kind"]]:
            raise RelayError(429, "rate_limited", "too many messages for this handle - try again later")
        with self.lock:
            self.db.execute("UPDATE push_handles SET window_start = ?, window_count = ?, last_used = ?, sent = sent + 1 "
                            "WHERE handle = ?", (start, count + 1, now, handle))
        res = await self.apns.send(row["token"], row["env"], payload, push_type, priority, collapse)
        if res.gone:
            with self.lock:
                self.db.execute("DELETE FROM push_handles WHERE handle = ?", (handle,))
            raise RelayError(410, "gone", "the phone no longer accepts this - register again")
        if not res.ok:
            raise RelayError(502, "apns_failed", f"APNs answered {res.status} {res.reason}".strip())
        return {"sent": True}

    def stats(self) -> dict[str, int]:
        with self.lock:
            rows = self.db.execute("SELECT kind, COUNT(*) AS n FROM push_handles GROUP BY kind").fetchall()
        return {r["kind"]: r["n"] for r in rows}
