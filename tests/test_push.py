"""Push notifications + Live Activities (0.51.0): APNs JWT, the relay, the notifier, the API."""
from __future__ import annotations

import asyncio
import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from fastapi.testclient import TestClient

from printshare.push import apns as apns_mod
from printshare.push import notify
from printshare.push import relay as relay_mod

from .test_cloud import cloud, login  # noqa: F401 - fixture

TOKEN_HEX = "ab" * 32


def run(coro):
    return asyncio.run(coro)


def pem_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


class FakeAPNs:
    def __init__(self, answer=None):
        self.sent = []
        self.answer = answer or apns_mod.Result(200)

    async def send(self, token, env, payload, push_type="alert", priority=10, collapse_id=None, expiration=None):
        self.sent.append({"token": token, "env": env, "payload": payload, "type": push_type, "priority": priority,
                          "collapse": collapse_id})
        return self.answer


def decrypt(key_b64: str, blob: str) -> dict:
    raw = base64.b64decode(blob)
    return json.loads(ChaCha20Poly1305(base64.b64decode(key_b64)).decrypt(raw[:12], raw[12:], None))


# ---------- APNs ----------
def test_es256_jwt_verifies_with_the_public_key():
    text = pem_key()
    key = apns_mod.load_key(text)
    jwt = apns_mod.es256_jwt(key, "KEYID12345", "TEAM123456", now=1000)
    head, claims, sig = jwt.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    assert json.loads(base64.urlsafe_b64decode(pad(head))) == {"alg": "ES256", "kid": "KEYID12345"}
    assert json.loads(base64.urlsafe_b64decode(pad(claims))) == {"iss": "TEAM123456", "iat": 1000}
    raw = base64.urlsafe_b64decode(pad(sig))
    assert len(raw) == 64, "JOSE signature = r || s, 32 bytes each (not DER)"
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_apns_result_gone():
    assert apns_mod.Result(410).gone and apns_mod.Result(400, "BadDeviceToken").gone
    assert not apns_mod.Result(429, "TooManyRequests").gone and apns_mod.Result(200).ok


# ---------- relay ----------
def test_relay_register_send_and_forget(tmp_path):
    fake = FakeAPNs()
    r = relay_mod.Relay(tmp_path / "relay.db", fake)
    reg = r.register(TOKEN_HEX, "device", "sandbox", ip="1.2.3.4")
    assert reg["handle"].startswith("pp3dp_")
    blob = base64.b64encode(b"x" * 40).decode()
    run(r.send(reg["handle"], reg["secret"], {"type": "alert", "data": blob, "level": "time-sensitive",
                                              "category": "SLOT_CHECK", "collapse": "j1-decision"}))
    sent = fake.sent[-1]
    assert sent["token"] == TOKEN_HEX and sent["env"] == "sandbox" and sent["type"] == "alert"
    aps = sent["payload"]["aps"]
    assert aps["mutable-content"] == 1 and aps["interruption-level"] == "time-sensitive"
    assert aps["category"] == "SLOT_CHECK" and aps["alert"] == {"loc-key": "push.fallback"}
    assert sent["payload"]["pp3d"] == blob and sent["collapse"] == "j1-decision"
    # wrong secret = unknown handle
    with pytest.raises(relay_mod.RelayError) as e:
        run(r.send(reg["handle"], "wrong-secret-xxxxxxxx", {"type": "alert", "data": blob}))
    assert e.value.status == 404
    # an activity message never goes to a device handle
    with pytest.raises(relay_mod.RelayError) as e:
        run(r.send(reg["handle"], reg["secret"], {"type": "activity", "event": "update", "state": {"s": "printing"}}))
    assert e.value.code == "wrong_handle"
    # same token again: the old handle is gone
    again = r.register(TOKEN_HEX, "device", "sandbox", ip="1.2.3.4")
    with pytest.raises(relay_mod.RelayError):
        r._row(reg["handle"], reg["secret"])
    # APNs says the token is dead → handle removed, 410 for the server
    fake.answer = apns_mod.Result(410, "Unregistered")
    with pytest.raises(relay_mod.RelayError) as e:
        run(r.send(again["handle"], again["secret"], {"type": "alert", "data": blob}))
    assert e.value.status == 410 and r.stats() == {}


def test_relay_live_activity_payloads_carry_numbers_only(tmp_path):
    fake = FakeAPNs()
    r = relay_mod.Relay(tmp_path / "relay.db", fake)
    act = r.register("cd" * 40, "activity", "production")
    start = r.register("ef" * 40, "start", "production")
    run(r.send(act["handle"], act["secret"], {"type": "activity", "event": "update",
                                              "state": {"s": "printing", "p": 42.6, "end": 2000, "name": "secret"}}))
    sent = fake.sent[-1]
    assert sent["type"] == "liveactivity" and sent["priority"] == 5
    assert sent["payload"]["aps"]["content-state"] == {"s": "printing", "p": 43, "end": 2000}, "unknown keys dropped"
    with pytest.raises(relay_mod.RelayError):
        run(r.send(act["handle"], act["secret"], {"type": "activity", "event": "update", "state": {"s": "boom"}}))
    run(r.send(start["handle"], start["secret"], {"type": "activity", "event": "start", "state": {"s": "printing"},
                                                  "attributes": {"job": "abc123", "printer": "dom"}}))
    aps = fake.sent[-1]["payload"]["aps"]
    assert aps["event"] == "start" and aps["attributes"] == {"job": "abc123", "printer": "dom"}
    assert aps["attributes-type"] == "PrintActivityAttributes" and fake.sent[-1]["priority"] == 10


def test_relay_rate_limits(tmp_path, monkeypatch):
    monkeypatch.setitem(relay_mod.LIMITS, "device", 2)
    r = relay_mod.Relay(tmp_path / "relay.db", FakeAPNs())
    reg = r.register(TOKEN_HEX, "device", "production")
    blob = base64.b64encode(b"y" * 40).decode()
    for _ in range(2):
        run(r.send(reg["handle"], reg["secret"], {"type": "alert", "data": blob}, now=1000))
    with pytest.raises(relay_mod.RelayError) as e:
        run(r.send(reg["handle"], reg["secret"], {"type": "alert", "data": blob}, now=1001))
    assert e.value.status == 429
    run(r.send(reg["handle"], reg["secret"], {"type": "alert", "data": blob}, now=1000 + 3601))


def test_relay_without_apns_key(tmp_path):
    r = relay_mod.Relay(tmp_path / "relay.db", None)
    reg = r.register(TOKEN_HEX, "device", "production")
    with pytest.raises(relay_mod.RelayError) as e:
        run(r.send(reg["handle"], reg["secret"], {"type": "alert", "data": "a" * 20}))
    assert e.value.status == 503


# ---------- notifier ----------
class Collect:
    def __init__(self):
        self.sent = []
        self.gone = set()

    async def __call__(self, handle, secret, msg):
        if handle in self.gone:
            raise notify.RelayGone(handle)
        self.sent.append((handle, msg))


def handle(n: int) -> str:
    return f"pp3dp_{'h' * 30}{n}"


def test_notifier_prefs_texts_and_once(tmp_path):
    out = Collect()
    n = notify.Notifier(tmp_path / "push.db", out)
    k1, k2 = notify.new_key(), notify.new_key()
    d1 = n.add("local", handle(1), "s" * 20, k1, "iPhone", "de-DE")
    n.add("local", handle(2), "s" * 20, k2, "iPad", "en", prefs={"done": False})
    job = {"id": "job1", "printer_file": "benchy.gcode"}
    assert run(n.emit("local", "finished", job, "dom", "Dominique", file="benchy")) == 1, "the iPad doesn't want 'done'"
    assert run(n.emit("local", "finished", job, "dom", "Dominique", file="benchy")) == 0, "once per job"
    h, msg = out.sent[-1]
    data = decrypt(k1, msg["data"])
    assert h == handle(1) and data["title"] == "Druck fertig" and data["body"] == "benchy auf Dominique ist fertig."
    assert data["job"] == "job1" and msg["level"] == "active" and msg["collapse"] == "job1-finished"
    # a problem goes to both, time-sensitive, in each phone's language
    problem = {"tool": 1, "lane": "lane2", "problem": "material", "expected": "PLA", "found": "PETG"}
    assert run(n.emit("local", "decision", job, "dom", "Dominique", once=False, problem_data=problem)) == 2
    texts = {h: decrypt(k1 if h == handle(1) else k2, m["data"])["body"] for h, m in out.sent[-2:]}
    assert texts[handle(1)].startswith("Slot 2 hat PETG statt PLA.") and "Dominique ist an" in texts[handle(1)]
    assert texts[handle(2)].startswith("Slot 2 holds PETG instead of PLA.")
    assert out.sent[-1][1]["category"] == "SLOT_CHECK" and out.sent[-1][1]["level"] == "time-sensitive"
    # muted printer, info off by default
    n.update("local", d1["id"], prefs={"muted": ["dom"]})
    assert run(n.emit("local", "error", job, "dom", once=False)) == 1
    assert run(n.emit("local", "external", {"id": "j2"}, "other")) == 0
    # the relay forgot a handle: the device is removed
    out.gone.add(handle(2))
    run(n.emit("local", "paused", job, "other", once=False))
    assert [d["name"] for d in n.devices("local")] == ["iPhone"]
    assert n.devices("someone-else") == []


def test_notifier_rejects_bad_keys(tmp_path):
    n = notify.Notifier(tmp_path / "push.db", Collect())
    with pytest.raises(notify.PushError):
        n.add("local", handle(1), "s" * 20, base64.b64encode(b"short").decode())
    with pytest.raises(notify.PushError):
        n.add("local", "not-a-handle", "s" * 20, notify.new_key())


def test_activity_state():
    now = 1000
    assert notify.activity_state({"state": "sending"}) == {"s": "sending", "p": 0}
    assert notify.activity_state({"state": "sending", "waking": True})["s"] == "waking"
    assert notify.activity_state({"state": "needs_decision"})["s"] == "decision"
    assert notify.activity_state({"state": "finished"}) == {"s": "done", "p": 100}
    assert notify.activity_state({"state": "sliced", "error": "x"})["s"] == "failed"
    st = notify.activity_state({"state": "started"}, {"progress": 25.0, "print_duration_s": 600, "layer": 10,
                                                      "layers": 40}, "active", now)
    assert st == {"s": "printing", "p": 25, "end": now + 1800, "l": 10, "lt": 40}
    st = notify.activity_state({"state": "started"}, {"progress": 50, "time_remaining_s": 60}, "paused", now)
    assert st == {"s": "paused", "p": 50}, "no end time while paused"


def test_activity_updates_are_throttled_and_end(tmp_path):
    out = Collect()
    n = notify.Notifier(tmp_path / "push.db", out)
    n.add_activity("local", "job1", handle(5), "s" * 20)
    job = {"id": "job1", "state": "started"}
    assert run(n.activity("local", job, {"progress": 10}, "active", now=1000)) == 1
    assert out.sent[-1][1]["urgent"] is True, "first message = state change"
    assert run(n.activity("local", job, {"progress": 12}, "active", now=1200)) == 0, "< 5 %"
    assert run(n.activity("local", job, {"progress": 16}, "active", now=1050)) == 0, "too soon"
    assert run(n.activity("local", job, {"progress": 16}, "active", now=1200)) == 1
    assert out.sent[-1][1]["urgent"] is False and out.sent[-1][1]["state"]["p"] == 16
    assert run(n.activity("local", job, {"progress": 16}, "paused", now=1210)) == 1, "state change right away"
    job["state"] = "finished"
    assert run(n.activity("local", job, now=1300)) == 1
    assert out.sent[-1][1]["event"] == "end" and not n.has_activity("local", "job1")


def test_push_to_start_only_for_devices_that_allow_it(tmp_path):
    out = Collect()
    n = notify.Notifier(tmp_path / "push.db", out)
    d = n.add("local", handle(1), "s" * 20, notify.new_key())
    job = {"id": "ext1", "state": "started"}
    assert run(n.start_activity("local", job, "dom")) == 0
    n.update("local", d["id"], start=(handle(9), "t" * 20))
    assert run(n.start_activity("local", job, "dom")) == 1
    assert out.sent[-1] == (handle(9), {"type": "activity", "event": "start", "state": {"s": "printing", "p": 0},
                                        "attributes": {"job": "ext1", "printer": "dom"},
                                        "stale": out.sent[-1][1]["stale"]})
    n.add_activity("local", "ext1", handle(7), "s" * 20)
    assert run(n.start_activity("local", job, "dom")) == 0, "the phone has one already"


# ---------- API (cloud: relay and notifier in one server) ----------
def test_cloud_register_device_and_test_push(cloud, tmp_path):  # noqa: F811
    api = cloud
    fake = FakeAPNs()
    api._RELAY = relay_mod.Relay(tmp_path / "relay.db", fake)
    with TestClient(api.app) as c:
        h = login(api, c, "push@example.com")
        info = c.get("/api/push", headers=h).json()
        assert info["relay_here"] is True and info["devices"] == [] and info["defaults"]["done"] is True
        reg = c.post("/push/register", json={"token": TOKEN_HEX, "kind": "device", "env": "sandbox"}).json()
        key = notify.new_key()
        dev = c.post("/api/push/devices", headers=h, json={**reg, "key": key, "name": "iPhone", "lang": "de"}).json()
        assert dev["name"] == "iPhone" and "secret" not in dev and "key" not in dev
        assert c.post(f"/api/push/devices/{dev['id']}/test", headers=h).json() == {"sent": True}
        assert decrypt(key, fake.sent[-1]["payload"]["pp3d"])["body"] == "Mitteilungen funktionieren."
        start = c.post("/push/register", json={"token": "cd" * 32, "kind": "start", "env": "sandbox"}).json()
        upd = c.put(f"/api/push/devices/{dev['id']}", headers=h,
                    json={"start_handle": start["handle"], "start_secret": start["secret"], "prefs": {"info": True}})
        assert upd.json()["live_activities"] is True and upd.json()["prefs"]["info"] is True
        # another account can't see or change it
        h2 = login(api, c, "other@example.com")
        assert c.get("/api/push", headers=h2).json()["devices"] == []
        assert c.delete(f"/api/push/devices/{dev['id']}", headers=h2).status_code == 404
        # bad messages are refused by the relay
        assert c.post("/push/send", json={"handle": reg["handle"], "secret": reg["secret"],
                                          "message": {"type": "nope"}}).status_code == 400
        assert c.delete(f"/api/push/devices/{dev['id']}", headers=h).status_code == 200


def test_home_server_has_no_relay(cloud, monkeypatch):  # noqa: F811
    api = cloud
    monkeypatch.setattr(api.settings, "cloud", False)
    with TestClient(api.app) as c:
        assert c.post("/push/register", json={"token": TOKEN_HEX}).status_code == 404


def test_cloud_learns_from_the_bridge_that_a_job_waits(cloud):  # noqa: F811
    api = cloud
    job = {"id": "cj1", "owner": "u1", "state": "sending", "log": [], "result": {"printer": "dom", "gcode": "/x/a.gcode"}}
    api.JOBS["cj1"] = job
    problem = {"tool": 0, "lane": "lane1", "problem": "material", "expected": "PLA", "found": "PETG"}
    api._bridge_event("b1", "someone-else", "job.decision", {"job": "cj1", "problems": [problem]})
    assert job["state"] == "sending", "another account's bridge can't touch the job"
    api._bridge_event("b1", "u1", "job.decision", {"job": "cj1", "problems": [problem], "until": 123})
    assert job["state"] == "needs_decision" and job["decision"] == {"until": 123, "problems": [problem]}
    api.JOBS.pop("cj1")


def test_orca_upload_and_print_starts_the_live_activity(cloud, monkeypatch):  # noqa: F811
    """0.53.1: a print OrcaSlicer starts through the server has no phone behind it - push-to-start its Live Activity."""
    api = cloud
    started = []

    async def fake_send(job_id, req, acct):
        api.JOBS[job_id]["state"] = "started"

    async def fake_start(owner, job, printer):
        started.append((owner, job["id"], printer, job["state"]))
        return 1

    monkeypatch.setattr(api, "send", fake_send)
    monkeypatch.setattr(api._notifier(), "start_activity", fake_start)
    monkeypatch.setattr(api, "BOOKINGS", None)
    job = {"id": "oj1", "owner": "u1", "printer": "cos", "state": "sliced", "log": [], "result": {"printer": "cos"}}
    api.JOBS["oj1"] = job
    try:
        run(api._orca_print(api.Account("u1", api.settings), job))
    finally:
        api.JOBS.pop("oj1")
    assert started == [("u1", "oj1", "cos", "started")]
