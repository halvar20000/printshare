"""Which phone hears about what (0.51.0): registered devices per account, events → encrypted notifications, Live
Activity updates for started jobs. One SQLite file per server (next to the cloud database / in the home config folder),
`owner` = cloud user id or "local".

Events (group → default):
  done       finished, cancelled                                   on
  problems   paused, error, ai_alert, send_failed                  on   (time-sensitive)
  decisions  decision (slot holds another material after waking)   on   (time-sensitive, actions "Prüfen"/"Abbrechen")
  info       external (print started elsewhere)                    off
`activities` (default on): Live Activity updates for this device's activities and push-to-start for prints the phone
didn't start itself.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

log = logging.getLogger(__name__)

GROUPS = {"finished": "done", "cancelled": "done", "paused": "problems", "error": "problems",
          "ai_alert": "problems", "send_failed": "problems", "decision": "decisions", "external": "info"}
DEFAULT_PREFS = {"done": True, "problems": True, "decisions": True, "info": False, "activities": True, "muted": []}
URGENT = ("problems", "decisions")
CATEGORIES = {"decision": "SLOT_CHECK", "ai_alert": "AI_ALERT"}
MAX_DEVICES = 10                  # per account
# Live Activity: progress at most every PROGRESS_STEP % and PROGRESS_MIN_S, a refresh at least every REFRESH_S
PROGRESS_STEP, PROGRESS_MIN_S, REFRESH_S = 5, 120, 15 * 60
ACTIVITY_MAX_AGE_S = 12 * 3600    # iOS ends a Live Activity after 8 h (+4 h on the lock screen)

# texts, German first (NF-11); {printer} {file} {problem} {reason}
TEXTS: dict[str, dict[str, tuple[str, str]]] = {
    "finished": {"de": ("Druck fertig", "{file} auf {printer} ist fertig."),
                 "en": ("Print finished", "{file} on {printer} is done.")},
    "cancelled": {"de": ("Druck abgebrochen", "{file} auf {printer} wurde abgebrochen."),
                  "en": ("Print cancelled", "{file} on {printer} was cancelled.")},
    "paused": {"de": ("Druck pausiert", "{printer} hat {file} angehalten und wartet auf dich."),
               "en": ("Print paused", "{printer} paused {file} and is waiting for you.")},
    "error": {"de": ("Druckerfehler", "{printer} meldet einen Fehler bei {file}."),
              "en": ("Printer error", "{printer} reports an error with {file}.")},
    "ai_alert": {"de": ("Möglicher Fehldruck", "Die KI-Fehlererkennung sieht ein Problem auf {printer}. Schau dir das "
                                               "Kamerabild an."),
                 "en": ("Possible print failure", "AI failure detection sees a problem on {printer}. Have a look at the "
                                                  "camera.")},
    "send_failed": {"de": ("Druck nicht gestartet", "{file} auf {printer}: {reason}"),
                    "en": ("Print not started", "{file} on {printer}: {reason}")},
    "decision": {"de": ("Falsches Material im Slot", "{problem} {printer} ist an und wartet. Prüfen oder abbrechen?"),
                 "en": ("Wrong material in the slot", "{problem} {printer} is on and waiting. Check or cancel?")},
    "external": {"de": ("Druck gestartet", "{printer} druckt {file}."),
                 "en": ("Print started", "{printer} is printing {file}.")},
    "test": {"de": ("PocketPrint3D", "Mitteilungen funktionieren."),
             "en": ("PocketPrint3D", "Notifications work.")},
}
PROBLEM_TEXT = {
    "material": {"de": "Slot {slot} hat {found} statt {expected}.", "en": "Slot {slot} holds {found} instead of {expected}."},
    "empty": {"de": "Slot {slot} ist leer.", "en": "Slot {slot} is empty."},
    "missing": {"de": "Slot {slot} fehlt.", "en": "Slot {slot} is missing."},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_devices (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL, handle TEXT NOT NULL, secret TEXT NOT NULL, key TEXT NOT NULL,
  platform TEXT NOT NULL, lang TEXT NOT NULL, name TEXT NOT NULL, prefs TEXT NOT NULL, start_handle TEXT,
  start_secret TEXT, created REAL NOT NULL, last_ok REAL, last_error TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS push_devices_handle ON push_devices(owner, handle);
CREATE TABLE IF NOT EXISTS push_activities (
  owner TEXT NOT NULL, job TEXT NOT NULL, handle TEXT NOT NULL, secret TEXT NOT NULL, device TEXT,
  created REAL NOT NULL, last_sent REAL NOT NULL DEFAULT 0, last_p REAL, last_s TEXT, PRIMARY KEY (owner, job, handle));
CREATE TABLE IF NOT EXISTS push_sent (
  owner TEXT NOT NULL, job TEXT NOT NULL, event TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (owner, job, event));
"""

# relay_send(handle, secret, message) → raises RelayGone when the handle is dead, any other exception = try later
Sender = Callable[[str, str, dict[str, Any]], Awaitable[Any]]


class PushError(ValueError):
    pass


class RelayGone(Exception):
    """The relay forgot the handle (app deleted, token renewed): drop it here too."""


def encrypt(key_b64: str, data: dict[str, Any]) -> str:
    """ChaCha20-Poly1305, CryptoKit's `ChaChaPoly.SealedBox(combined:)` layout: nonce (12) + ciphertext + tag (16)."""
    key = base64.b64decode(key_b64)
    nonce = os.urandom(12)
    return base64.b64encode(nonce + ChaCha20Poly1305(key).encrypt(nonce, json.dumps(data).encode(), None)).decode()


def _lang(lang: str) -> str:
    return "de" if str(lang or "").lower().startswith("de") else "en"


def problem_text(problem: dict[str, Any], lang: str) -> str:
    tpl = PROBLEM_TEXT.get(problem.get("problem") or "", PROBLEM_TEXT["material"])[_lang(lang)]
    lane = problem.get("lane") or ""
    m = re.search(r"(\d+)$", str(lane))
    slot = m.group(1) if m else str((problem.get("tool") or 0) + 1)
    return tpl.format(slot=slot, found=problem.get("found") or "?", expected=problem.get("expected") or "?")


def text(event: str, lang: str, **fields: Any) -> tuple[str, str]:
    title, body = TEXTS[event][_lang(lang)]
    defaults = {"printer": "", "file": "", "problem": "", "reason": ""}
    defaults.update({k: ("" if v is None else str(v)) for k, v in fields.items()})
    body = body.format(**defaults)
    return title, re.sub(r"\s+", " ", body).strip()[:300]


def _thread(printer: str) -> str:
    return "p" + hashlib.sha256(printer.encode()).hexdigest()[:12]


def activity_state(job: dict[str, Any], status: dict[str, Any] | None = None, kind: str | None = None,
                   now: float | None = None) -> dict[str, Any]:
    """Content state of a job's Live Activity (numbers and a state code only, see relay.py)."""
    now = now or time.time()
    st = job.get("state")
    if st == "finished":
        return {"s": "done", "p": 100}
    if st == "cancelled":
        return {"s": "cancelled", "p": int(job.get("progress") or 0)}
    if st == "needs_decision":
        return {"s": "decision", "p": 0}
    if st in ("sending", "uploading"):
        return {"s": "waking" if job.get("waking") else "sending", "p": 0}
    if st != "started":
        return {"s": "failed" if job.get("error") else "cancelled", "p": int(job.get("progress") or 0)}
    status = status or {}
    p = status.get("progress")
    p = float(p) if isinstance(p, (int, float)) and not isinstance(p, bool) else float(job.get("progress") or 0)
    out: dict[str, Any] = {"s": {"paused": "paused", "error": "error"}.get(kind or "", "printing"), "p": round(p)}
    remaining = status.get("time_remaining_s")
    elapsed = status.get("print_duration_s")
    if not isinstance(remaining, (int, float)) and isinstance(elapsed, (int, float)) and 2 <= p < 100:
        remaining = elapsed * (100 - p) / p
    if isinstance(remaining, (int, float)) and remaining >= 0 and out["s"] == "printing":
        out["end"] = int(now + remaining)
    for key, src in (("l", "layer"), ("lt", "layers")):
        val = status.get(src)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            out[key] = val
    return out


class Notifier:
    def __init__(self, path: str | Path, sender: Sender | None) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()
        self.sender = sender

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    # ---------- devices ----------
    @staticmethod
    def public(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"], "platform": row["platform"], "lang": row["lang"],
                "prefs": {**DEFAULT_PREFS, **json.loads(row["prefs"])}, "live_activities": bool(row["start_handle"]),
                "created": row["created"], "last_ok": row["last_ok"], "last_error": row["last_error"]}

    def devices(self, owner: str) -> list[dict[str, Any]]:
        return [self.public(r) for r in self._q("SELECT * FROM push_devices WHERE owner = ? ORDER BY created", (owner,))]

    def _device(self, owner: str, device_id: str) -> sqlite3.Row:
        rows = self._q("SELECT * FROM push_devices WHERE owner = ? AND id = ?", (owner, device_id))
        if not rows:
            raise KeyError(device_id)
        return rows[0]

    @staticmethod
    def _prefs(prefs: dict[str, Any] | None, base: dict[str, Any] | None = None) -> dict[str, Any]:
        out = dict(base or DEFAULT_PREFS)
        for key, val in (prefs or {}).items():
            if key == "muted" and isinstance(val, list):
                out["muted"] = [str(p)[:64] for p in val if isinstance(p, str)][:50]
            elif key in DEFAULT_PREFS and isinstance(val, bool):
                out[key] = val
        return out

    def add(self, owner: str, handle: str, secret: str, key: str, name: str = "", lang: str = "de",
            platform: str = "ios", prefs: dict[str, Any] | None = None, now: float | None = None) -> dict[str, Any]:
        try:
            if len(base64.b64decode(key, validate=True)) != 32:
                raise ValueError
        except (ValueError, TypeError):
            raise PushError("key must be 32 random bytes in base64") from None
        if not re.fullmatch(r"pp3dp_[A-Za-z0-9_-]{22,40}", handle or "") or not 16 <= len(secret or "") <= 100:
            raise PushError("handle and secret come from the push relay")
        if platform not in ("ios", "android"):
            raise PushError("unknown platform")
        now = now or time.time()
        name, lang = str(name or "")[:60], _lang(lang)
        existing = self._q("SELECT * FROM push_devices WHERE owner = ? AND handle = ?", (owner, handle))
        if existing:
            row = existing[0]
            with self.lock:
                self.db.execute("UPDATE push_devices SET secret = ?, key = ?, name = ?, lang = ?, prefs = ? WHERE id = ?",
                                (secret, key, name, lang, json.dumps(self._prefs(prefs, json.loads(row["prefs"]))),
                                 row["id"]))
            return self.public(self._device(owner, row["id"]))
        if len(self._q("SELECT id FROM push_devices WHERE owner = ?", (owner,))) >= MAX_DEVICES:
            raise PushError(f"at most {MAX_DEVICES} phones per account")
        device_id = uuid.uuid4().hex[:12]
        with self.lock:
            self.db.execute("INSERT INTO push_devices (id, owner, handle, secret, key, platform, lang, name, prefs, created)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (device_id, owner, handle, secret, key, platform, lang, name,
                             json.dumps(self._prefs(prefs)), now))
        return self.public(self._device(owner, device_id))

    def update(self, owner: str, device_id: str, prefs: dict[str, Any] | None = None, lang: str | None = None,
               name: str | None = None, start: tuple[str, str] | None = None) -> dict[str, Any]:
        row = self._device(owner, device_id)
        fields: dict[str, Any] = {}
        if prefs is not None:
            fields["prefs"] = json.dumps(self._prefs(prefs, {**DEFAULT_PREFS, **json.loads(row["prefs"])}))
        if lang is not None:
            fields["lang"] = _lang(lang)
        if name is not None:
            fields["name"] = str(name)[:60]
        if start is not None:
            handle, secret = start
            if handle and not re.fullmatch(r"pp3dp_[A-Za-z0-9_-]{22,40}", handle):
                raise PushError("start_handle comes from the push relay")
            fields["start_handle"], fields["start_secret"] = (handle or None), (secret or None)
        if fields:
            with self.lock:
                self.db.execute(f"UPDATE push_devices SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                                (*fields.values(), device_id))
        return self.public(self._device(owner, device_id))

    def remove(self, owner: str, device_id: str) -> None:
        self._device(owner, device_id)
        with self.lock:
            self.db.execute("DELETE FROM push_devices WHERE id = ?", (device_id,))
            self.db.execute("DELETE FROM push_activities WHERE owner = ? AND device = ?", (owner, device_id))

    def remove_owner(self, owner: str) -> None:
        with self.lock:
            for table in ("push_devices", "push_activities", "push_sent"):
                self.db.execute(f"DELETE FROM {table} WHERE owner = ?", (owner,))

    # ---------- sending ----------
    async def _send(self, handle: str, secret: str, msg: dict[str, Any]) -> bool:
        if self.sender is None:
            return False
        await self.sender(handle, secret, msg)
        return True

    async def _to_device(self, row: sqlite3.Row, msg: dict[str, Any]) -> bool:
        try:
            ok = await self._send(row["handle"], row["secret"], msg)
        except RelayGone:
            with self.lock:
                self.db.execute("DELETE FROM push_devices WHERE id = ?", (row["id"],))
            return False
        except Exception as e:  # noqa: BLE001 - relay unreachable, rate limited …: the next event tries again
            with self.lock:
                self.db.execute("UPDATE push_devices SET last_error = ? WHERE id = ?", (str(e)[:200], row["id"]))
            log.info("push to %s failed: %s", row["id"], e)
            return False
        if ok:
            with self.lock:
                self.db.execute("UPDATE push_devices SET last_ok = ?, last_error = NULL WHERE id = ?",
                                (time.time(), row["id"]))
        return ok

    async def emit(self, owner: str, event: str, job: dict[str, Any] | None = None, printer: str = "",
                   printer_name: str = "", once: bool = True, **fields: Any) -> int:
        """Send one event to every device of the account that wants it. With `once`, an event is sent once per job."""
        group = GROUPS.get(event)
        job_id = (job or {}).get("id") or ""
        if once and job_id:
            with self.lock:
                cur = self.db.execute("INSERT OR IGNORE INTO push_sent (owner, job, event, at) VALUES (?, ?, ?, ?)",
                                      (owner, job_id, event, time.time()))
                if cur.rowcount == 0:
                    return 0
        sent = 0
        for row in self._q("SELECT * FROM push_devices WHERE owner = ?", (owner,)):
            prefs = {**DEFAULT_PREFS, **json.loads(row["prefs"])}
            if event != "test" and (not group or not prefs.get(group) or printer in prefs.get("muted", [])):
                continue
            extra = dict(fields)
            problem = extra.pop("problem_data", None)
            if isinstance(problem, dict):
                extra["problem"] = problem_text(problem, row["lang"])
            title, body = text(event, row["lang"], printer=printer_name or printer, **extra)
            data = {"event": event, "title": title, "body": body, "job": job_id or None, "printer": printer or None}
            msg = {"type": "alert", "data": encrypt(row["key"], data),
                   "level": "time-sensitive" if group in URGENT else "active",
                   "category": CATEGORIES.get(event), "thread": _thread(printer) if printer else None,
                   "collapse": f"{job_id}-{event}"[:64] if job_id else None}
            if await self._to_device(row, msg):
                sent += 1
        return sent

    async def test(self, owner: str, device_id: str) -> bool:
        row = self._device(owner, device_id)
        title, body = text("test", row["lang"])
        msg = {"type": "alert", "data": encrypt(row["key"], {"event": "test", "title": title, "body": body}),
               "level": "active"}
        try:
            return await self._send(row["handle"], row["secret"], msg)
        except RelayGone:
            raise PushError("the phone is no longer registered with the push relay - open the app again") from None

    # ---------- Live Activities ----------
    def add_activity(self, owner: str, job_id: str, handle: str, secret: str, device: str | None = None) -> None:
        if not re.fullmatch(r"pp3dp_[A-Za-z0-9_-]{22,40}", handle or "") or not 16 <= len(secret or "") <= 100:
            raise PushError("handle and secret come from the push relay")
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO push_activities (owner, job, handle, secret, device, created) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (owner, job_id, handle, secret, device, time.time()))

    def has_activity(self, owner: str, job_id: str) -> bool:
        return bool(self._q("SELECT 1 FROM push_activities WHERE owner = ? AND job = ?", (owner, job_id)))

    async def activity(self, owner: str, job: dict[str, Any], status: dict[str, Any] | None = None,
                       kind: str | None = None, now: float | None = None) -> int:
        """Bring the job's Live Activities up to date (throttled); ends them when the job is over."""
        now = now or time.time()
        rows = self._q("SELECT * FROM push_activities WHERE owner = ? AND job = ?", (owner, job["id"]))
        if not rows:
            return 0
        state = activity_state(job, status, kind, now)
        final = state["s"] in ("done", "cancelled", "failed")
        sent = 0
        for row in rows:
            changed = state["s"] != row["last_s"]
            p_step = row["last_p"] is None or abs(state.get("p", 0) - row["last_p"]) >= PROGRESS_STEP
            due = changed or (p_step and now - row["last_sent"] >= PROGRESS_MIN_S) or now - row["last_sent"] >= REFRESH_S
            if not due:
                continue
            msg: dict[str, Any] = {"type": "activity", "event": "end" if final else "update", "state": state,
                                   "urgent": changed, "stale": int(now + 30 * 60)}
            try:
                await self._send(row["handle"], row["secret"], msg)
            except RelayGone:
                final = True               # the activity is gone on the phone: forget it
            except Exception as e:  # noqa: BLE001
                log.info("live activity update for %s failed: %s", job["id"], e)
                continue
            sent += 1
            with self.lock:
                if final or now - row["created"] > ACTIVITY_MAX_AGE_S:
                    self.db.execute("DELETE FROM push_activities WHERE owner = ? AND job = ? AND handle = ?",
                                    (owner, job["id"], row["handle"]))
                else:
                    self.db.execute("UPDATE push_activities SET last_sent = ?, last_p = ?, last_s = ? "
                                    "WHERE owner = ? AND job = ? AND handle = ?",
                                    (now, state.get("p", 0), state["s"], owner, job["id"], row["handle"]))
        return sent

    async def start_activity(self, owner: str, job: dict[str, Any], printer: str) -> int:
        """Push-to-start on every device that allows it, for a print the phone didn't start (external, OrcaSlicer)."""
        if self.has_activity(owner, job["id"]):
            return 0
        sent = 0
        for row in self._q("SELECT * FROM push_devices WHERE owner = ? AND start_handle IS NOT NULL", (owner,)):
            prefs = {**DEFAULT_PREFS, **json.loads(row["prefs"])}
            if not prefs.get("activities") or printer in prefs.get("muted", []):
                continue
            msg = {"type": "activity", "event": "start", "state": activity_state(job),
                   "attributes": {"job": job["id"], "printer": printer}, "stale": int(time.time() + 30 * 60)}
            try:
                await self._send(row["start_handle"], row["start_secret"], msg)
                sent += 1
            except RelayGone:
                with self.lock:
                    self.db.execute("UPDATE push_devices SET start_handle = NULL, start_secret = NULL WHERE id = ?",
                                    (row["id"],))
            except Exception as e:  # noqa: BLE001
                log.info("push-to-start for %s failed: %s", job["id"], e)
        return sent


def new_key() -> str:
    """For tests and the web app: 32 random bytes in base64."""
    return base64.b64encode(secrets.token_bytes(32)).decode()
