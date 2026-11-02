"""Inbox folder (0.49.0): model files that appear in a watched folder show up in the apps.

Meant for a CAD program on the same machine (e.g. the SolidCraft container's `/workspace`, mounted read-only
as `/inbox`): whatever it exports there is offered on the home screen, a tap opens the prepare page.
Nothing is sliced or printed by itself.

- Only own servers (never the cloud). Folder = `Settings.inbox_dir` (env PRINTSHARE_INBOX, default `/inbox` when
  that folder exists, "off" switches it off).
- Scanned every few seconds, subfolders up to `MAX_DEPTH`, hidden files/folders skipped, symlinks not followed.
- A file counts once its size and mtime stayed the same for one scan and it is at least `SETTLE_S` old (still
  being written otherwise). It is then copied into the uploads (`upload:<id>` link) so a later overwrite or
  delete in the folder doesn't change a prepared job. A changed file (new size/mtime) is offered again.
- Files already there when the inbox is first switched on are not offered (a big workspace would flood the list).
- State in `<work_dir>/inbox.json`; at most `MAX_ITEMS` entries, older ones (and their upload copies) dropped.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fetch import SLICEABLE

SCAN_S = 5
SETTLE_S = 3
MAX_DEPTH = 4
MAX_ITEMS = 30
MAX_FILES = 5000           # scan stops there (a mounted disk instead of a folder)
MAX_SIZE = 300 * 1024 * 1024


@dataclass
class Inbox:
    folder: Path
    uploads: Path
    state_file: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _pending: dict[str, tuple[int, float]] = field(default_factory=dict, repr=False)

    # ---------- state ----------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_file.read_text())
            if isinstance(data, dict) and isinstance(data.get("seen"), dict) and isinstance(data.get("items"), list):
                return data
        except (OSError, ValueError):
            pass
        return {"seen": {}, "items": [], "baseline": False}

    def _save(self, data: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self.state_file)

    # ---------- scanning ----------
    def _files(self) -> dict[str, tuple[int, float]]:
        out: dict[str, tuple[int, float]] = {}
        base = self.folder
        stack: list[tuple[Path, int]] = [(base, 0)]
        while stack and len(out) < MAX_FILES:
            d, depth = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        if depth + 1 < MAX_DEPTH:
                            stack.append((Path(e.path), depth + 1))
                    elif e.is_file(follow_symlinks=False) and e.name.lower().endswith(SLICEABLE):
                        st = e.stat(follow_symlinks=False)
                        out[Path(e.path).relative_to(base).as_posix()] = (st.st_size, st.st_mtime)
                except OSError:
                    continue
        return out

    def scan(self, now: float | None = None) -> list[dict[str, Any]]:
        """One pass; returns the items added by it."""
        now = time.time() if now is None else now
        if not self.folder.is_dir():
            return []
        files = self._files()
        added: list[dict[str, Any]] = []
        with self._lock:
            data = self._load()
            seen: dict[str, list] = data["seen"]
            if not data.get("baseline"):
                # first run: what is there already is not "new"
                data["seen"] = {k: [v[0], v[1]] for k, v in files.items()}
                data["baseline"] = True
                self._save(data)
                return []
            changed = False
            for rel, (size, mtime) in files.items():
                old = seen.get(rel)
                if old and old[0] == size and old[1] == mtime:
                    self._pending.pop(rel, None)
                    continue
                # wait until the file stopped changing (two equal scans) and is a few seconds old
                if self._pending.get(rel) != (size, mtime) or now - mtime < SETTLE_S:
                    self._pending[rel] = (size, mtime)
                    continue
                self._pending.pop(rel, None)
                seen[rel] = [size, mtime]
                changed = True
                if size == 0 or size > MAX_SIZE:
                    continue
                item = self._copy(rel, size, mtime, now)
                if item:
                    data["items"] = [i for i in data["items"] if i["path"] != rel]
                    data["items"].insert(0, item)
                    added.append(item)
            for rel in list(seen):
                if rel not in files:
                    del seen[rel]
                    changed = True
            for rel in list(self._pending):
                if rel not in files:
                    del self._pending[rel]
            if len(data["items"]) > MAX_ITEMS:
                for old in data["items"][MAX_ITEMS:]:
                    self._drop_copy(old)
                data["items"] = data["items"][:MAX_ITEMS]
                changed = True
            if changed:
                self._save(data)
        return added

    def _copy(self, rel: str, size: int, mtime: float, now: float) -> dict[str, Any] | None:
        src = self.folder / rel
        uid = uuid.uuid4().hex[:12]
        d = self.uploads / uid
        name = Path(rel).name
        try:
            d.mkdir(parents=True)
            shutil.copyfile(src, d / name)
        except OSError:
            shutil.rmtree(d, ignore_errors=True)
            return None
        return {"id": uid, "name": name, "path": rel, "size": size, "modified": mtime, "found": now,
                "link": f"upload:{uid}"}

    def _drop_copy(self, item: dict[str, Any]) -> None:
        uid = str(item.get("id", ""))
        if len(uid) == 12 and uid.isalnum():
            shutil.rmtree(self.uploads / uid, ignore_errors=True)

    # ---------- API ----------
    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._load()["items"])

    def dismiss(self, item_id: str | None = None) -> int:
        """Remove one entry (or all with None) from the list; the file in the folder stays."""
        with self._lock:
            data = self._load()
            keep, gone = [], []
            for i in data["items"]:
                (gone if item_id is None or i["id"] == item_id else keep).append(i)
            if gone:
                for i in gone:
                    self._drop_copy(i)
                data["items"] = keep
                self._save(data)
            return len(gone)


def for_settings(settings: Any) -> Inbox | None:
    if settings.cloud or getattr(settings, "bridge_only", False):
        return None
    folder = str(getattr(settings, "inbox_dir", "") or "").strip()
    if not folder or folder.lower() in ("off", "0", "false", "no"):
        return None
    work = Path(settings.work_dir)
    return Inbox(Path(folder), work / "uploads", work / "inbox.json")
