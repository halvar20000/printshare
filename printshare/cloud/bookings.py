"""Spool bookings in the cloud account (docs/WEB.md step 2): which print uses how much of which spool, and booking the
grams on the account's spools (cloud/spools.py) once the print is finished.

The app creates a booking when it starts a print with spools chosen. Whoever sees the printer reports its status:
the cloud itself for printers behind a bridge (it asks the bridge, so nothing has to be open), the app for printers it
reaches on the Wi-Fi. `judge()` decides - the same rules as the phone used before (mobile/src/lib/spoolman.ts):
  finished                          → book everything
  cancelled / error                 → ask the user, suggesting the printed share
  never seen printing (20 min)      → ask
  printer unreachable for 3 days    → ask
Booked uses are removed one by one, so a retry never books twice.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from typing import Any

from .accounts import AccountError, Accounts

WAIT_START_S = 20 * 60          # heating + leveling can take a while before the file shows up
GIVE_UP_S = 3 * 24 * 3600       # printer never seen again
MAX_OPEN = 50                   # open bookings per account
KEEP_BOOKED_S = 15 * 60         # booked ones are shown ("3.7 g booked") for a while, then deleted

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, printer TEXT NOT NULL,
  printer_name TEXT, file TEXT NOT NULL, job TEXT, uses TEXT NOT NULL, booked_uses TEXT NOT NULL DEFAULT '[]',
  created REAL NOT NULL, seen INTEGER NOT NULL DEFAULT 0, progress REAL, state TEXT NOT NULL DEFAULT 'wait',
  ask_part REAL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS bookings_user ON bookings(user_id, state);
"""


def same_file(a: str | None, b: str | None) -> bool:
    """The same print? File names on the printer may be shortened or cleaned up (PrusaLink: plain FAT names)."""
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", re.sub(r"\.[^.]+$", "", s.split("/")[-1]).lower())
    return bool(a) and bool(b) and bool(norm(b)) and norm(a) == norm(b)


def judge(b: dict[str, Any], st: dict[str, Any] | None, now: float) -> dict[str, Any]:
    """New state of a waiting booking given the printer's status now (None = not reachable). Pure."""
    if b["state"] != "wait":
        return b
    age = now - b["created"]
    progress = b.get("progress")
    if st is None:
        return {**b, "state": "ask", "ask_part": 1.0} if age > GIVE_UP_S else b
    if same_file(st.get("file"), b["file"]):
        if isinstance(st.get("progress"), (int, float)):
            progress = float(st["progress"])
        kind = st.get("kind")
        if kind in ("active", "paused"):
            return {**b, "seen": True, "progress": progress}
        if kind == "done":
            return {**b, "state": "ready"}
        if kind in ("stopped", "error"):
            return {**b, "state": "ask", "ask_part": min(1.0, (progress or 0) / 100)}
        # idle with the file still shown (e.g. PrusaLink after FINISHED)
        if b["seen"] and (b.get("progress") or 0) >= 99:
            return {**b, "state": "ready"}
        if b["seen"]:
            return {**b, "state": "ask", "ask_part": min(1.0, (b.get("progress") or 0) / 100)}
        return {**b, "state": "ask", "ask_part": 1.0} if age > WAIT_START_S else b
    # the printer shows something else now: finished unseen (nobody was looking) or replaced
    if b["seen"]:
        return {**b, "state": "ready"} if (b.get("progress") or 0) >= 99 else \
            {**b, "state": "ask", "ask_part": min(1.0, (b.get("progress") or 0) / 100)}
    return {**b, "state": "ask", "ask_part": 1.0} if age > WAIT_START_S else b


class Bookings:
    def __init__(self, accounts: Accounts, spools) -> None:
        self.acc = accounts
        self.spools = spools
        with accounts.lock:
            accounts.db.executescript(SCHEMA)

    @staticmethod
    def _row(r: Any) -> dict[str, Any]:
        return {"id": r["id"], "printer": r["printer"], "printer_name": r["printer_name"], "file": r["file"],
                "job": r["job"], "uses": json.loads(r["uses"]), "booked_uses": json.loads(r["booked_uses"]),
                "created": r["created"], "seen": bool(r["seen"]), "progress": r["progress"], "state": r["state"],
                "ask_part": r["ask_part"], "updated": r["updated"]}

    def _save(self, user_id: str, b: dict[str, Any], now: float) -> None:
        self.acc._q("UPDATE bookings SET uses = ?, booked_uses = ?, seen = ?, progress = ?, state = ?, ask_part = ?, "
                    "updated = ? WHERE id = ? AND user_id = ?",
                    (json.dumps(b["uses"]), json.dumps(b["booked_uses"]), int(b["seen"]), b.get("progress"),
                     b["state"], b.get("ask_part"), now, b["id"], user_id))

    # ---------- create / read ----------
    def create(self, user_id: str, printer: str, file: str, uses: list[dict[str, Any]], printer_name: str | None = None,
               job: str | None = None, now: float | None = None) -> dict[str, Any] | None:
        now = now or time.time()
        clean = []
        for u in uses if isinstance(uses, list) else []:
            try:
                spool, grams = int(u["spool"]), float(u["grams"])
            except (KeyError, TypeError, ValueError):
                raise AccountError("each use needs spool (number) and grams")
            if spool < 1 or not 0 <= grams <= 100_000:
                raise AccountError("spool must be ≥ 1 and grams between 0 and 100000")
            self.spools.get(user_id, spool)                     # 404 for a spool that isn't the account's
            clean.append({"spool": spool, "grams": round(grams, 3), "label": str(u.get("label") or "")[:120]})
        if not clean:
            return None
        if not (file or "").strip():
            raise AccountError("file is missing")
        with self.acc.lock:
            db = self.acc.db
            # a new print replaces one on the same printer that never started
            db.execute("DELETE FROM bookings WHERE user_id = ? AND printer = ? AND state = 'wait' AND seen = 0",
                       (user_id, printer))
            if db.execute("SELECT COUNT(*) FROM bookings WHERE user_id = ? AND state IN ('wait', 'ask')",
                          (user_id,)).fetchone()[0] >= MAX_OPEN:
                raise AccountError(f"at most {MAX_OPEN} open bookings - decide the open ones first", 409)
            bid = secrets.token_hex(8)
            db.execute("INSERT INTO bookings (id, user_id, printer, printer_name, file, job, uses, created, updated) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (bid, user_id, printer, (printer_name or printer)[:60], file.strip()[:200], job,
                        json.dumps(clean), now, now))
        return self.get(user_id, bid)

    def get(self, user_id: str, bid: str) -> dict[str, Any]:
        rows = self.acc._q("SELECT * FROM bookings WHERE id = ? AND user_id = ?", (bid, user_id))
        if not rows:
            raise AccountError("unknown booking", 404)
        return self._row(rows[0])

    def list(self, user_id: str, now: float | None = None) -> dict[str, list[dict[str, Any]]]:
        """{"waiting", "open" (the user decides), "booked" (recently, for a short notice)}"""
        now = now or time.time()
        self.acc._q("DELETE FROM bookings WHERE user_id = ? AND state IN ('booked', 'dropped') AND updated < ?",
                    (user_id, now - KEEP_BOOKED_S))
        rows = [self._row(r) for r in self.acc._q("SELECT * FROM bookings WHERE user_id = ? ORDER BY created", (user_id,))]
        return {"waiting": [b for b in rows if b["state"] in ("wait", "ready")],
                "open": [b for b in rows if b["state"] == "ask"],
                "booked": [b for b in rows if b["state"] == "booked"]}

    def waiting_printers(self) -> list[tuple[str, str]]:
        """(user, printer) pairs with bookings waiting for a status - for the cloud's own check of bridge printers."""
        return [(r["user_id"], r["printer"]) for r in
                self.acc._q("SELECT DISTINCT user_id, printer FROM bookings WHERE state IN ('wait', 'ready')")]

    # ---------- settle ----------
    def _book(self, user_id: str, b: dict[str, Any], part: float, now: float) -> None:
        """Book `part` of what is left; each spool is removed from the list right after it was booked."""
        while b["uses"]:
            u = b["uses"][0]
            grams = round(u["grams"] * part, 3)
            if grams >= 0.05:
                try:
                    self.spools.use(user_id, u["spool"], grams)
                except AccountError as e:
                    if e.status != 404:                         # a deleted spool is skipped, anything else retried
                        raise
                    grams = 0
            b["booked_uses"].append({**u, "grams": grams})
            b["uses"].pop(0)
            self._save(user_id, b, now)
        b["state"] = "booked"
        self._save(user_id, b, now)

    def observe(self, user_id: str, printer: str, status: dict[str, Any] | None, now: float | None = None) -> list[dict[str, Any]]:
        """A printer's status was seen (by the app or the cloud): judge its waiting bookings, book finished ones.
        Returns the bookings booked now."""
        now = now or time.time()
        booked = []
        for r in self.acc._q("SELECT * FROM bookings WHERE user_id = ? AND printer = ? AND state IN ('wait', 'ready')",
                             (user_id, printer)):
            b = self._row(r)
            new = judge(b, status, now)
            if new != b:
                self._save(user_id, new, now)
            if new["state"] == "ready":
                self._book(user_id, new, 1.0, now)
                booked.append(new)
        return booked

    def resolve(self, user_id: str, bid: str, part: float, now: float | None = None) -> dict[str, Any]:
        """The user's decision on an open booking: book `part` (0 = nothing, 1 = everything)."""
        now = now or time.time()
        if not 0 <= part <= 1:
            raise AccountError("part must be between 0 and 1")
        b = self.get(user_id, bid)
        if b["state"] not in ("ask", "wait"):
            raise AccountError("this booking is already settled", 409)
        if part > 0:
            self._book(user_id, b, part, now)
        else:
            b["state"] = "dropped"
            self._save(user_id, b, now)
        return self.get(user_id, bid)

    def delete(self, user_id: str, bid: str) -> bool:
        with self.acc.lock:
            return self.acc.db.execute("DELETE FROM bookings WHERE id = ? AND user_id = ?", (bid, user_id)).rowcount > 0
