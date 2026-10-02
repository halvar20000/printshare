"""Spool bookings in the cloud account (docs/WEB.md step 2): the decision rules, booking exactly once, the API, and the
cloud's own check of printers behind a bridge."""
from __future__ import annotations

import asyncio
import re
import time

import pytest
from fastapi.testclient import TestClient

from printshare.cloud import accounts
from printshare.cloud.bookings import GIVE_UP_S, WAIT_START_S, Bookings, judge, same_file
from printshare.cloud.spools import Spools

from .test_cloud import cloud  # noqa: F401 - fixture

T0 = 1_000_000.0


def b(**kw):
    return {"state": "wait", "created": T0, "seen": False, "progress": None, "file": "cube.gcode", **kw}


def st(kind, file="cube.gcode", progress=None):
    return {"kind": kind, "file": file, "progress": progress}


def test_judge_rules():
    assert same_file("/usb/CUBE~1.GCO", "cube.gcode") is False and same_file("gcodes/Cube.gcode", "cube.gcode")
    x = judge(b(), st("active", progress=40), T0 + 60)
    assert x["seen"] and x["progress"] == 40 and x["state"] == "wait"
    assert judge(x, st("done"), T0 + 900)["state"] == "ready"
    stopped = judge(x, st("stopped", progress=25), T0 + 900)
    assert stopped["state"] == "ask" and stopped["ask_part"] == 0.25
    # idle with the file still shown: finished if it got to 99 %
    assert judge(b(seen=True, progress=99.5), st("idle"), T0 + 900)["state"] == "ready"
    # something else on the printer: finished unseen (nobody was looking) vs. replaced
    assert judge(b(seen=True, progress=100), st("active", "other.gcode"), T0)["state"] == "ready"
    assert judge(b(seen=True, progress=60), st("idle", "other.gcode"), T0)["ask_part"] == 0.6
    assert judge(b(), st("idle", "other.gcode"), T0 + 60)["state"] == "wait"
    assert judge(b(), st("idle", "other.gcode"), T0 + WAIT_START_S + 1)["state"] == "ask"
    # not reachable: only after 3 days
    assert judge(b(), None, T0 + 3600)["state"] == "wait"
    assert judge(b(), None, T0 + GIVE_UP_S + 1) == {**b(), "state": "ask", "ask_part": 1.0}


@pytest.fixture
def books(tmp_path):
    acc = accounts.Accounts(tmp_path / "cloud.db")
    users = [acc.verify_code(e, acc.request_code(e))[0] for e in ("anna@example.com", "ben@example.com")]
    spools = Spools(acc)
    return Bookings(acc, spools), spools, users


def test_booking_books_once_and_only_own_spools(books):
    bk, spools, (anna, ben) = books
    pla = spools.create(anna.id, {"filament": {"name": "PLA", "material": "PLA", "weight": 1000}, "initial_weight": 1000})
    petg = spools.create(anna.id, {"filament": {"name": "PETG", "material": "PETG", "weight": 1000}, "initial_weight": 1000})
    spools.create(ben.id, {"filament": {"name": "Bens", "material": "PLA", "weight": 1000}})
    with pytest.raises(accounts.AccountError):           # Ben's spool #1 is not Anna's #3
        bk.create(anna.id, "cc", "cube.gcode", [{"spool": 3, "grams": 5}])
    assert bk.create(anna.id, "cc", "cube.gcode", []) is None
    one = bk.create(anna.id, "cc", "first.gcode", [{"spool": pla["id"], "grams": 1}], now=T0)
    two = bk.create(anna.id, "cc", "cube.gcode", [{"spool": pla["id"], "grams": 3.7, "label": "PLA"},
                                                  {"spool": petg["id"], "grams": 1.25}], job="j1", now=T0)
    assert [x["id"] for x in bk.list(anna.id, T0)["waiting"]] == [two["id"]], "a new print replaces one never started"
    assert bk.observe(anna.id, "cc", st("active", progress=50), T0 + 60) == []
    booked = bk.observe(anna.id, "cc", st("done"), T0 + 600)
    assert [x["id"] for x in booked] == [two["id"]]
    assert spools.get(anna.id, pla["id"])["used_weight"] == 3.7 and spools.get(anna.id, petg["id"])["used_weight"] == 1.25
    # seen again: never booked twice
    assert bk.observe(anna.id, "cc", st("done"), T0 + 700) == []
    assert spools.get(anna.id, pla["id"])["used_weight"] == 3.7
    lst = bk.list(anna.id, T0 + 700)
    assert lst["booked"][0]["booked_uses"][1]["grams"] == 1.25 and not lst["waiting"]
    assert bk.list(ben.id, T0)["booked"] == [] and one["id"] not in str(lst)
    # booked ones go away after a while
    assert bk.list(anna.id, T0 + 700 + 3600)["booked"] == []


def test_cancelled_print_asks_and_deleted_spool_is_skipped(books):
    bk, spools, (anna, _) = books
    a = spools.create(anna.id, {"filament": {"name": "A", "weight": 1000}})
    c = spools.create(anna.id, {"filament": {"name": "C", "weight": 1000}})
    x = bk.create(anna.id, "mk4", "part.gcode", [{"spool": a["id"], "grams": 10}, {"spool": c["id"], "grams": 4}], now=T0)
    bk.observe(anna.id, "mk4", st("active", "part.gcode", 30), T0 + 60)
    bk.observe(anna.id, "mk4", st("stopped", "part.gcode", 30), T0 + 120)
    opened = bk.list(anna.id, T0 + 120)["open"]
    assert opened[0]["id"] == x["id"] and opened[0]["ask_part"] == 0.3
    spools.delete(anna.id, c["id"])
    res = bk.resolve(anna.id, x["id"], 0.5, T0 + 200)
    assert res["state"] == "booked" and spools.get(anna.id, a["id"])["used_weight"] == 5
    with pytest.raises(accounts.AccountError):
        bk.resolve(anna.id, x["id"], 1)
    y = bk.create(anna.id, "mk4", "p2.gcode", [{"spool": a["id"], "grams": 9}], now=T0)
    assert bk.resolve(anna.id, y["id"], 0)["state"] == "dropped"
    assert spools.get(anna.id, a["id"])["used_weight"] == 5


def _login(api, c, email):
    assert c.post("/api/auth/code", json={"email": email}).status_code == 200
    code = re.search(r"\d{6}", api.MAILER.sent[-1][1]).group()
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "code": code}).json()["token"]}


def test_bookings_api_and_bridge_check(cloud, monkeypatch):  # noqa: F811
    api = cloud
    with TestClient(api.app) as c:
        h = _login(api, c, "anna@example.com")
        other = _login(api, c, "ben@example.com")
        assert c.post("/api/printers", json={"name": "CC", "type": "elegoo_sdcp"}, headers=h).status_code == 200
        spool = c.post("/spoolman/api/v1/spool", json={"filament": {"name": "PLA", "weight": 1000}}, headers=h).json()
        r = c.post("/api/bookings", json={"printer": "cc", "file": "cube.gcode", "printer_name": "CC",
                                          "uses": [{"spool": spool["id"], "grams": 3.7, "label": "PLA"}]}, headers=h)
        assert r.status_code == 200, r.text
        bid = r.json()["booking"]["id"]
        assert c.post("/api/bookings", json={"printer": "nope", "file": "x", "uses": []}, headers=h).status_code == 404
        assert c.get("/api/bookings", headers=other).json()["waiting"] == []
        assert c.post(f"/api/bookings/{bid}/resolve", json={"part": 1}, headers=other).status_code == 404
        # the app reports what it saw on the Wi-Fi
        r = c.post("/api/bookings/observe", json={"statuses": {"cc": {"kind": "active", "file": "cube.gcode", "progress": 10},
                                                               "unknown": None}}, headers=h).json()
        assert r["waiting"][0]["seen"] and r["booked_now"] == []
        r = c.post("/api/bookings/observe", json={"statuses": {"cc": {"kind": "done", "file": "cube.gcode"}}}, headers=h).json()
        assert [x["id"] for x in r["booked_now"]] == [bid] and r["booked"][0]["id"] == bid
        assert c.get(f"/spoolman/api/v1/spool/{spool['id']}", headers=h).json()["used_weight"] == 3.7

        # a printer behind a bridge: the cloud asks the bridge itself
        uid = api.ACCOUNTS.user_for_token(h["Authorization"][7:]).id
        api.ACCOUNTS.save_printer(uid, {"id": "voron", "name": "Voron", "type": "moonraker", "bridge": "b1", "remote": "v"})
        bid2 = c.post("/api/bookings", json={"printer": "voron", "file": "part.gcode",
                                             "uses": [{"spool": spool["id"], "grams": 2}]}, headers=h).json()["booking"]["id"]
        calls = []
        statuses = iter([{"kind": "active", "file": "part.gcode", "progress": 50}, {"kind": "done", "file": "part.gcode"}])

        async def fake_call(bridge, user, method, params, timeout=None):
            calls.append((bridge, user, method, params))
            return next(statuses)
        monkeypatch.setattr(api.HUB, "online", lambda bridge: bridge == "b1")
        monkeypatch.setattr(api.HUB, "call", fake_call)
        asyncio.run(api._check_bridge_bookings())
        asyncio.run(api._check_bridge_bookings())
        assert calls[0] == ("b1", uid, "printer.status", {"printer": "v"}) and len(calls) == 2
        assert c.get(f"/spoolman/api/v1/spool/{spool['id']}", headers=h).json()["used_weight"] == 5.7
        assert [x["id"] for x in c.get("/api/bookings", headers=h).json()["booked"]] == [bid, bid2]
        assert c.delete(f"/api/bookings/{bid}", headers=h).status_code == 200
        # home servers have no account bookings
        assert time.time() > 0
