"""Inbox folder (0.49.0): new model files in a watched folder are offered in the apps."""
import os
import time
from types import SimpleNamespace

from printshare import inbox as inbox_mod
from printshare.inbox import Inbox, for_settings


def _box(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    work = tmp_path / "work"
    return Inbox(folder, work / "uploads", work / "inbox.json"), folder, work


def _write(path, data=b"solid x\nendsolid x\n", age=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    t = time.time() - age
    os.utime(path, (t, t))


def test_existing_files_are_baseline_new_ones_settle_first(tmp_path):
    box, folder, work = _box(tmp_path)
    _write(folder / "old.stl")
    assert box.scan() == []                      # first run: what is there is not new
    _write(folder / "part.stl")
    assert box.scan() == []                      # seen once: may still be written
    added = box.scan()
    assert [i["name"] for i in added] == ["part.stl"]
    item = added[0]
    assert item["link"] == f"upload:{item['id']}"
    assert (work / "uploads" / item["id"] / "part.stl").read_bytes() == (folder / "part.stl").read_bytes()
    assert box.scan() == []                      # not offered twice
    assert [i["path"] for i in box.items()] == ["part.stl"]


def test_fresh_file_waits_for_settle_time(tmp_path):
    box, folder, _ = _box(tmp_path)
    box.scan()
    _write(folder / "fresh.3mf", age=0)
    now = time.time()
    assert box.scan(now) == [] and box.scan(now) == []
    assert [i["name"] for i in box.scan(now + inbox_mod.SETTLE_S + 1)] == ["fresh.3mf"]


def test_changed_file_is_offered_again_and_copy_kept(tmp_path):
    box, folder, work = _box(tmp_path)
    box.scan()
    _write(folder / "sub" / "clip.stl", b"v1")
    box.scan()
    first = box.scan()[0]
    assert first["path"] == "sub/clip.stl"
    _write(folder / "sub" / "clip.stl", b"version 2", age=5)
    box.scan()
    second = box.scan()[0]
    assert second["id"] != first["id"]
    assert [i["id"] for i in box.items()] == [second["id"]]           # one entry per path
    assert (work / "uploads" / second["id"] / "clip.stl").read_bytes() == b"version 2"


def test_skips_hidden_unsupported_and_empty(tmp_path):
    box, folder, _ = _box(tmp_path)
    box.scan()
    _write(folder / ".hidden.stl")
    _write(folder / ".cache" / "x.stl")
    _write(folder / "notes.txt")
    _write(folder / "design.sc")
    _write(folder / "empty.stl", b"")
    box.scan()
    assert box.scan() == []


def test_dismiss_removes_entry_and_copy(tmp_path):
    box, folder, work = _box(tmp_path)
    box.scan()
    _write(folder / "a.stl")
    _write(folder / "b.obj")
    box.scan()
    box.scan()
    ids = {i["name"]: i["id"] for i in box.items()}
    assert box.dismiss(ids["a.stl"]) == 1
    assert not (work / "uploads" / ids["a.stl"]).exists()
    assert (folder / "a.stl").exists()                                 # the folder itself is never touched
    assert box.dismiss("nope") == 0
    assert box.dismiss(None) == 1 and box.items() == []


def test_list_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_mod, "MAX_ITEMS", 2)
    box, folder, work = _box(tmp_path)
    box.scan()
    for n in range(3):
        _write(folder / f"p{n}.stl", age=10 + n)
    box.scan()
    box.scan()
    assert len(box.items()) == 2
    assert len(list((work / "uploads").iterdir())) == 2


def test_for_settings(tmp_path):
    base = dict(cloud=False, bridge_only=False, work_dir=str(tmp_path), inbox_dir=str(tmp_path / "in"))
    assert for_settings(SimpleNamespace(**base)).folder == tmp_path / "in"
    assert for_settings(SimpleNamespace(**{**base, "cloud": True})) is None
    assert for_settings(SimpleNamespace(**{**base, "bridge_only": True})) is None
    assert for_settings(SimpleNamespace(**{**base, "inbox_dir": "off"})) is None
    assert for_settings(SimpleNamespace(**{**base, "inbox_dir": ""})) is None
