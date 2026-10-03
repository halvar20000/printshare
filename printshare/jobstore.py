"""Jobs that survive a restart (cloud: every update restarts the server; home servers too).

The API keeps working on its in-memory dict of jobs (they are changed in many places while slicing and sending); this
store mirrors it into SQLite: `sync()` writes the jobs that changed since the last call and removes deleted ones. It is
called every few seconds and on shutdown. `load()` brings them back after a start - jobs that were still slicing or
sending are marked as interrupted (their worker is gone). Cleanup (BE-05): jobs older than `max_age_days` and the
oldest beyond `keep_per_owner` go, with their G-code folder.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

RUNNING = ("slicing", "sending", "running", "uploading")
INTERRUPTED = {
    "uploading": ("error", "The upload was interrupted by a server update - please send it again."),
    "slicing": ("error", "Interrupted by a server update - please slice again."),
    "running": ("error", "Interrupted by a server update - please try again."),
    "sending": ("sliced", "Sending was interrupted by a server update - please send again."),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created);
"""


def job_dir(job: dict[str, Any]) -> Path | None:
    """The job's own G-code folder (<gcode dir>/<printer>/<job id>), None if it has none."""
    gcode = (job.get("result") or {}).get("gcode")
    if not gcode:
        return None
    d = Path(gcode).parent
    return d if d.name == job.get("id") else None


class JobStore:
    def __init__(self, path: str | Path, keep_per_owner: int = 50, max_age_days: float = 14) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()
        self.keep = keep_per_owner
        self.max_age_s = max_age_days * 86400
        self._hashes: dict[str, str] = {}

    @staticmethod
    def _dump(job: dict[str, Any]) -> str:
        return json.dumps(job, sort_keys=True, default=str)

    def load(self) -> dict[str, dict[str, Any]]:
        """All stored jobs; ones that were still running when the server stopped are marked as interrupted."""
        jobs: dict[str, dict[str, Any]] = {}
        with self.lock:
            rows = self.db.execute("SELECT id, data FROM jobs ORDER BY created").fetchall()
        for jid, data in rows:
            try:
                job = json.loads(data)
            except ValueError:
                continue
            if job.get("state") in INTERRUPTED:
                state, error = INTERRUPTED[job["state"]]
                if state == "sliced" and not job.get("result"):
                    state = "error"
                job.update(state=state, error=error)
            jobs[jid] = job
            self._hashes[jid] = ""            # written again with the new state on the next sync
        return jobs

    def sync(self, jobs: dict[str, dict[str, Any]], now: float | None = None) -> int:
        """Write changed jobs, delete removed ones. Returns how many rows were written."""
        now = now or time.time()
        changed = []
        for jid, job in list(jobs.items()):
            try:
                data = self._dump(job)
            except (TypeError, ValueError, RuntimeError):   # changed while being written (thread): next round
                continue
            h = hashlib.sha1(data.encode()).hexdigest()
            if self._hashes.get(jid) != h:
                changed.append((jid, str(job.get("owner", "local")), float(job.get("created") or now), now, data, h))
        gone = [jid for jid in self._hashes if jid not in jobs]
        if not changed and not gone:
            return 0
        with self.lock:
            self.db.execute("BEGIN")
            try:
                for jid, owner, created, updated, data, _ in changed:
                    self.db.execute("INSERT INTO jobs (id, owner, created, updated, data) VALUES (?, ?, ?, ?, ?) "
                                    "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated = excluded.updated",
                                    (jid, owner, created, updated, data))
                for jid in gone:
                    self.db.execute("DELETE FROM jobs WHERE id = ?", (jid,))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        for jid, *_, h in changed:
            self._hashes[jid] = h
        for jid in gone:
            self._hashes.pop(jid, None)
        return len(changed)

    def prune(self, jobs: dict[str, dict[str, Any]], now: float | None = None) -> list[str]:
        """Forget old jobs (and their G-code): older than max_age, and per owner beyond keep_per_owner.
        Running jobs are never touched. Changes `jobs` in place; the next sync removes them from the database."""
        now = now or time.time()
        by_owner: dict[str, list[dict[str, Any]]] = {}
        for job in list(jobs.values()):
            by_owner.setdefault(str(job.get("owner", "local")), []).append(job)
        drop = []
        for owned in by_owner.values():
            owned.sort(key=lambda j: j.get("created") or 0, reverse=True)
            for i, job in enumerate(owned):
                if job.get("state") in RUNNING:
                    continue
                if i >= self.keep or now - (job.get("created") or now) > self.max_age_s:
                    drop.append(job)
        for job in drop:
            jobs.pop(job["id"], None)
            d = job_dir(job)
            if d is not None:
                shutil.rmtree(d, ignore_errors=True)
        return [j["id"] for j in drop]
