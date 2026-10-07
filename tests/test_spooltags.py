"""Spools by NFC chip and per slot, NFC readers at the printer (printshare/spooltags.py, 0.38.0)."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from printshare import spooltags
from .test_cloud import cloud, login  # noqa: F401 - fixture


def test_store(tmp_path):
    s = spooltags.SpoolTags(tmp_path / "t.db")
    assert spooltags.normalize_uid("04:a2:3b:1c 5d:6e:80") == "04A23B1C5D6E80"
    with pytest.raises(spooltags.TagError):
        spooltags.normalize_uid("xyz")
    # a reader sees an unknown chip in slot 1 → remembered, no spool yet
    assert s.scan("u1", "p1s", 1, "04a23b1c") is None
    assert s.scans("u1", "p1s")["1"]["uid"] == "04A23B1C" and s.slots("u1", "p1s") == {}
    # linking the chip later puts the spool into that slot
    s.link("u1", "04A23B1C", 17)
    assert s.slots("u1", "p1s")["1"]["spool"] == 17 and s.slots("u1", "p1s")["1"]["source"] == "reader"
    # a spool sits in one slot only: moving it (even to another printer) clears the old slot
    s.set_slot("u1", "cc", 254, 17)
    assert s.slots("u1", "p1s") == {} and s.slots("u1", "cc")["254"]["spool"] == 17
    # a second chip on the same spool (Bambu: one on each side) and owners don't see each other
    s.link("u1", "11223344", 17)
    assert s.spool_for("u1", "11223344") == 17 and s.spool_for("u2", "11223344") is None
    assert s.scan("u1", "p1s", 2, "11223344") == 17 and s.slots("u1", "p1s")["2"]["spool"] == 17
    # reader keys: stored as hash, one per printer
    key = s.create_key("u1", "p1s")
    assert key.startswith("pp3dr_") and s.resolve_key(key) == ("u1", "p1s") and s.resolve_key("pp3dr_x") is None
    assert s.resolve_key(s.create_key("u1", "p1s")) == ("u1", "p1s") and s.resolve_key(key) is None   # replaced
    s.forget_printer("u1", "p1s")
    assert s.slots("u1", "p1s") == {} and s.key_info("u1", "p1s") is None
    s.forget_owner("u1")
    assert s.links("u1") == []


@pytest.fixture
def home(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n"
                   "printers:\n  - id: cc\n    type: elegoo_sdcp\n    host: 192.168.1.10\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    return importlib.reload(importlib.import_module("printshare.api"))


def test_home_server_endpoints(home):
    c = TestClient(home.app)
    h = {"Authorization": "Bearer t"}
    assert c.get("/api/spool-tags/04A23B1C", headers=h).json() == {"uid": "04A23B1C", "spool": None}
    assert c.put("/api/spool-tags/04a23b1c", headers=h, json={"spool": 5}).json() == {"uid": "04A23B1C", "spool": 5}
    assert c.get("/api/spool-tags", headers=h).json()[0]["spool"] == 5
    assert c.put("/api/spool-tags/zz", headers=h, json={"spool": 5}).status_code == 400
    # the app puts a spool into a slot
    r = c.put("/api/printers/cc/slot-spools/254", headers=h, json={"spool": 9})
    assert r.status_code == 200 and r.json()["slots"]["254"]["spool"] == 9 and r.json()["printer_set"] is False
    assert c.put("/api/printers/nope/slot-spools/1", headers=h, json={"spool": 9}).status_code == 404
    # an NFC reader with its key (no printer needed) - known chip → the spool sits in the slot
    key = c.post("/api/printers/cc/reader-key", headers=h).json()["key"]
    r = c.post("/api/reader/scan", headers={"Authorization": f"Bearer {key}"}, json={"slot": 254, "uid": "04A23B1C"})
    assert r.json() == {"known": True, "spool": 5, "printer_set": False}
    slots = c.get("/api/printers/cc/slot-spools", headers=h).json()
    assert slots["slots"]["254"]["spool"] == 5 and slots["scans"]["254"]["uid"] == "04A23B1C"
    # unknown chip: remembered for the app; the server token works too, with the printer named
    r = c.post("/api/reader/scan", headers={"X-Api-Key": key}, json={"slot": 1, "uid": "AABBCCDD"})
    assert r.json()["known"] is False
    assert c.post("/api/reader/scan", headers=h, json={"slot": 1, "uid": "AABBCCDD"}).status_code == 400   # no printer
    assert c.post("/api/reader/scan", headers=h, json={"slot": 1, "uid": "AABBCCDD", "printer": "cc"}).json()["known"] is False
    assert c.post("/api/reader/scan", headers={"Authorization": "Bearer pp3dr_wrong"},
                  json={"slot": 1, "uid": "AABBCCDD"}).status_code == 401
    assert c.get("/api/printers/cc/reader-key", headers=h).json()["enabled"] is True


def test_cloud_endpoints_and_account_isolation(cloud):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        a = login(api, c, "a@example.com")
        b = login(api, c, "b@example.com")
        c.post("/api/printers", headers=a, json={"name": "CC", "type": "elegoo_sdcp"})
        spool = c.post("/spoolman/api/v1/spool", headers=a,
                       json={"filament": {"material": "PLA", "color_hex": "E02020", "weight": 1000}}).json()["id"]
        c.put("/api/spool-tags/04A23B1C", headers=a, json={"spool": spool})
        assert c.get("/api/spool-tags/04A23B1C", headers=b).json()["spool"] is None         # other account
        key = c.post("/api/printers/cc/reader-key", headers=a).json()["key"]
        r = c.post("/api/reader/scan", headers={"Authorization": f"Bearer {key}"}, json={"slot": 254, "uid": "04A23B1C"})
        # known → slot set; the printer is reached by the phone (no bridge): it can't be told from here
        assert r.json() == {"known": True, "spool": spool, "printer_set": False}
        assert c.get("/api/printers/cc/slot-spools", headers=a).json()["slots"]["254"]["spool"] == spool
        assert c.get("/api/printers/cc/slot-spools", headers=b).status_code == 404
        # deleting the printer forgets its slots and reader key
        c.delete("/api/printers/cc", headers=a)
        uid = api.ACCOUNTS.user_for_token(a["Authorization"].removeprefix("Bearer ")).id
        assert api._tags().key_info(uid, "cc") is None and api._tags().slots(uid, "cc") == {}


# ---------- where spools are kept: cloud or the user's Spoolman (0.39.0) ----------
def test_spool_source_helpers():
    from printshare import spool_source
    assert spool_source.check_url("192.168.1.20:7912/") == "http://192.168.1.20:7912"
    assert spool_source.candidates("http://spoolman.local") == ["http://spoolman.local", "http://spoolman.local:7912"]
    with pytest.raises(ValueError):
        spool_source.check_url("ftp://x y")


def test_home_server_tells_the_printer_from_spoolman(home, monkeypatch):
    import socket
    from .fakes import FakeSpoolman
    from .test_api import BackgroundFake
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    told: list = []

    async def fake_filament_action(printer_id, req, acct):
        told.append((printer_id, req.action, req.slot, req.material, req.color))
        return {"ok": True}
    monkeypatch.setattr(home, "filament_action", fake_filament_action)
    c = TestClient(home.app)
    h = {"Authorization": "Bearer t"}
    assert c.get("/api/spool-source", headers=h).json() == {"source": "spoolman", "spoolman_url": None,
                                                           "server_reaches_spoolman": False}
    assert c.put("/api/spool-source", headers=h, json={"source": "cloud"}).status_code == 400   # home: Spoolman only
    with BackgroundFake(FakeSpoolman(port)):
        r = c.put("/api/spool-source", headers=h, json={"source": "spoolman", "spoolman_url": f"127.0.0.1:{port}"})
        assert r.json()["server_reaches_spoolman"] is True
        c.put("/api/spool-tags/04A23B1C", headers=h, json={"spool": 4})                # Spoolman #4: PETG white
        r = c.post("/api/reader/scan", headers=h, json={"slot": 2, "uid": "04A23B1C", "printer": "cc"})
        assert r.json() == {"known": True, "spool": 4, "printer_set": True}
        assert told == [("cc", "set", 2, "PETG", "#FFFFFF")]
        # the bridge methods: the cloud passes the address on, and asks the bridge to tell a printer
        from printshare.bridge.dispatch import dispatch
        import asyncio
        assert asyncio.run(dispatch("spoolman.config", {"url": f"http://127.0.0.1:{port}"}, None)) == \
            {"spoolman_url": f"http://127.0.0.1:{port}"}
        assert asyncio.run(dispatch("printer.slot.sync", {"printer": "cc", "tool": 1, "spool": 3}, None)) == {"printer_set": True}
        assert told[-1] == ("cc", "set", 1, "PLA", "#000000")


def test_cloud_account_chooses_spoolman(cloud):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        a = login(api, c, "a@example.com")
        assert c.get("/api/spool-source", headers=a).json()["source"] == "cloud"
        r = c.put("/api/spool-source", headers=a, json={"source": "spoolman", "spoolman_url": "192.168.1.20"})
        assert r.json()["source"] == "spoolman" and r.json()["bridges_set"] == 0      # no bridge online
        c.post("/api/printers", headers=a, json={"name": "CC", "type": "elegoo_sdcp"})
        r = c.put("/api/printers/cc/slot-spools/254", headers=a, json={"spool": 7})
        # printer on the phone's Wi-Fi with a Spoolman spool: the app tells the printer, not the cloud
        assert r.json()["printer_set"] is False and r.json()["slots"]["254"]["spool"] == 7
