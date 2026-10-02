"""Bridges, cloud side (docs/BRIDGE.md step 2): pairing, bridge tokens, the WebSocket hub, G-code for bridges."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
import websockets
from fastapi import Depends

from printshare.cloud import accounts
from printshare.cloud.bridges import Bridges
from .test_cloud import cloud  # noqa: F401 - fixture

KEY = base64.b64encode(bytes(range(32))).decode()


# ---------- pairing in the database ----------
@pytest.fixture
def db(tmp_path):
    acc = accounts.Accounts(tmp_path / "cloud.db")
    users = []
    for email in ("anna@example.com", "ben@example.com"):
        code = acc.request_code(email)
        users.append(acc.verify_code(email, code)[0])
    return acc, Bridges(acc), users


def test_pairing_flow(db):
    acc, br, (anna, ben) = db
    bid = str(uuid.uuid4())
    start = br.start_pairing(bid, KEY, "0.24.0", "Tower", ip="1.2.3.4")
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", start["code"])
    assert br.poll_pairing(bid, start["poll"])["status"] == "waiting"
    with pytest.raises(accounts.AccountError):
        br.poll_pairing(bid, "wrong poll secret")
    b = br.confirm_pairing(anna.id, start["code"].lower().replace("-", " "))    # typed sloppily
    assert b["name"] == "Tower" and b["public_key"] == KEY and b["version"] == "0.24.0"
    paired = br.poll_pairing(bid, start["poll"])
    assert paired["status"] == "paired" and paired["token"].startswith("pp3db_") and paired["account"] == anna.email
    with pytest.raises(accounts.AccountError):              # the token is handed out once
        br.poll_pairing(bid, start["poll"])
    assert br.for_token(paired["token"])["user_id"] == anna.id
    assert br.for_token("pp3db_nope") is None and br.for_token("pp3d_session") is None
    assert [x["id"] for x in br.list(anna.id)] == [bid] and br.list(ben.id) == []
    with pytest.raises(accounts.AccountError):              # a used code is gone
        br.confirm_pairing(ben.id, start["code"])
    # pairing again (here: to Ben) revokes the old token and moves the bridge
    again = br.start_pairing(bid, KEY, "0.24.1")
    br.confirm_pairing(ben.id, again["code"], name="Werkstatt")
    new = br.poll_pairing(bid, again["poll"])["token"]
    assert br.for_token(paired["token"]) is None and br.for_token(new)["user_id"] == ben.id
    assert br.list(anna.id) == [] and br.list(ben.id)[0]["name"] == "Werkstatt"
    # rename, delete; deleting the account removes its bridges
    assert br.rename(ben.id, bid, " Keller ")["name"] == "Keller"
    acc.delete_user(ben.id)
    assert br.for_token(new) is None and br.count() == 0


def test_pairing_limits(db):
    acc, br, (anna, _) = db
    with pytest.raises(accounts.AccountError):
        br.start_pairing("short")
    with pytest.raises(accounts.AccountError):
        br.start_pairing(str(uuid.uuid4()), public_key="not base64!")
    # codes expire
    old = br.start_pairing(str(uuid.uuid4()), now=time.time() - 3600)
    with pytest.raises(accounts.AccountError) as e:
        br.confirm_pairing(anna.id, old["code"])
    assert e.value.status == 404
    # wrong codes are limited per user
    for _ in range(5):
        with pytest.raises(accounts.AccountError):
            br.confirm_pairing(anna.id, "AAAA-AAAA")
    good = br.start_pairing(str(uuid.uuid4()))
    with pytest.raises(accounts.AccountError) as e:
        br.confirm_pairing(anna.id, good["code"])
    assert e.value.status == 429
    # pair starts are limited per network
    for _ in range(20):
        br.start_pairing(str(uuid.uuid4()), ip="9.9.9.9")
    with pytest.raises(accounts.AccountError) as e:
        br.start_pairing(str(uuid.uuid4()), ip="9.9.9.9")
    assert e.value.status == 429


# ---------- the whole path over HTTP + WebSocket ----------
@pytest.fixture
def live(cloud):  # noqa: F811
    api = cloud

    @api.app.get("/test/bridge-call/{bridge_id}")       # stands in for the forwarded printer endpoints (step 4)
    async def _call(bridge_id: str, method: str, timeout: float | None = None, acct=Depends(api.auth)):
        try:
            return {"result": await api.HUB.call(bridge_id, acct.id, method, {"printer": "cc"}, timeout)}
        except api.BridgeError as e:
            return {"error": e.code, "status": e.status, "message": str(e)}

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    yield api, f"127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


async def _login(api, c, email):
    assert (await c.post("/api/auth/code", json={"email": email})).status_code == 200
    code = re.search(r"\d{6}", api.MAILER.sent[-1][1]).group()
    r = await c.post("/api/auth/login", json={"email": email, "code": code})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _closed(ws) -> int:
    with pytest.raises(websockets.ConnectionClosed):
        for _ in range(5):
            await asyncio.wait_for(ws.recv(), 5)
    return ws.close_code


def test_bridge_end_to_end(live, tmp_path):
    api, host = live

    async def run():
        async with httpx.AsyncClient(base_url=f"http://{host}") as c:
            anna = await _login(api, c, "anna@example.com")
            ben = await _login(api, c, "ben@example.com")
            bid = str(uuid.uuid4())
            # pairing: bridge asks for a code, Anna enters it in the app, the bridge picks up its token
            start = (await c.post("/api/bridge/pair/start", json={"bridge_id": bid, "public_key": KEY,
                                                                   "version": "0.24.0", "name": "Tower"})).json()
            assert (await c.post("/api/bridge/pair/poll", json={"bridge_id": bid, "poll": start["poll"]})).json()["status"] == "waiting"
            r = await c.post("/api/bridges/pair", json={"code": "ZZZZ-ZZZZ"}, headers=anna)
            assert r.status_code == 404 and "code" in r.json()["detail"]
            r = await c.post("/api/bridges/pair", json={"code": start["code"]}, headers=anna)
            assert r.status_code == 200 and r.json()["online"] is False and r.json()["name"] == "Tower"
            token = (await c.post("/api/bridge/pair/poll", json={"bridge_id": bid, "poll": start["poll"]})).json()["token"]
            auth = {"Authorization": f"Bearer {token}"}

            url = f"ws://{host}/api/bridge/ws"
            # unknown token / too old
            async with websockets.connect(url, additional_headers={"Authorization": "Bearer pp3db_nope"}) as ws:
                assert await _closed(ws) == 4401
            async with websockets.connect(url, additional_headers=auth) as ws:
                await ws.send(json.dumps({"type": "hello", "version": "0.23.0", "printers": []}))
                assert await _closed(ws) == 4426

            # connected: hello with printers (the address must not end up in the cloud)
            ws = await websockets.connect(url, additional_headers=auth)
            await ws.send(json.dumps({"type": "hello", "bridge_id": bid, "version": "0.24.0", "printers": [
                {"id": "cc", "name": "Centauri", "type": "elegoo_sdcp", "address": "192.168.1.5",
                 "capabilities": {"camera": True}}]}))
            welcome = json.loads(await ws.recv())
            assert welcome["type"] == "welcome" and "job.send" in welcome["methods"]
            lst = (await c.get("/api/bridges", headers=anna)).json()
            assert lst[0]["online"] is True and lst[0]["printers"] == [
                {"id": "cc", "name": "Centauri", "type": "elegoo_sdcp", "capabilities": {"camera": True}}]
            assert (await c.get("/api/bridges", headers=ben)).json() == []

            # the fake bridge answers requests
            seen = []

            async def bridge_loop(sock):
                try:
                    await _answer(sock)
                except websockets.ConnectionClosed:
                    pass

            async def _answer(sock):
                async for text in sock:
                    msg = json.loads(text)
                    seen.append(msg)
                    if msg["method"] == "printer.status":
                        await sock.send(json.dumps({"id": msg["id"], "type": "res", "ok": True,
                                                    "result": {"state": "printing", "kind": "active", "progress": 42}}))
                    elif msg["method"] == "printer.control":
                        await sock.send(json.dumps({"id": msg["id"], "type": "res", "ok": False,
                                                    "error": {"code": "offline", "message": "printer not reachable"}}))
                    # "discover": never answered → timeout

            loop_task = asyncio.create_task(bridge_loop(ws))
            r = (await c.get(f"/test/bridge-call/{bid}", params={"method": "printer.status"}, headers=anna)).json()
            assert r == {"result": {"state": "printing", "kind": "active", "progress": 42}}
            assert seen[-1]["params"] == {"printer": "cc"} and seen[-1]["type"] == "req"
            r = (await c.get(f"/test/bridge-call/{bid}", params={"method": "printer.control"}, headers=anna)).json()
            assert r == {"error": "offline", "status": 503, "message": "printer not reachable"}
            r = (await c.get(f"/test/bridge-call/{bid}", params={"method": "discover", "timeout": 0.3}, headers=anna)).json()
            assert r["error"] == "bridge_timeout" and r["status"] == 504
            r = (await c.get(f"/test/bridge-call/{bid}", params={"method": "printer.status"}, headers=ben)).json()
            assert r["error"] == "bridge_offline", "another account can't use Anna's bridge"

            # events
            await ws.send(json.dumps({"type": "event", "event": "printer.state",
                                      "data": {"printer": "cc", "kind": "active", "progress": 50}}))
            await ws.send(json.dumps({"type": "event", "event": "printers.changed", "data": {"printers": [
                {"id": "cc", "name": "Centauri"}, {"id": "p1s", "name": "P1S", "type": "bambu_lan", "access_code": "x"}]}}))
            await asyncio.sleep(0.2)
            assert api.HUB.conns[bid].states["cc"]["progress"] == 50
            assert [p["id"] for p in (await c.get("/api/bridges", headers=anna)).json()[0]["printers"]] == ["cc", "p1s"]
            assert "access_code" not in api.HUB.conns[bid].printers[1]

            # G-code for a job of the bridge's account only, with the bridge token only
            g = tmp_path / "cube.gcode"
            g.write_text("G1 X1 Y1\n")
            uid_anna = api.ACCOUNTS.user_for_token(anna["Authorization"][7:]).id
            uid_ben = api.ACCOUNTS.user_for_token(ben["Authorization"][7:]).id
            api.JOBS["jobanna"] = {"id": "jobanna", "owner": uid_anna, "state": "sliced", "created": time.time(),
                                   "result": {"gcode": str(g), "source_file": "cube.stl", "printer": "cc"}}
            api.JOBS["jobben"] = {**api.JOBS["jobanna"], "id": "jobben", "owner": uid_ben}
            r = await c.get("/api/bridge/jobs/jobanna/gcode", headers=auth)
            assert r.status_code == 200 and r.text == "G1 X1 Y1\n"
            assert (await c.get("/api/bridge/jobs/jobben/gcode", headers=auth)).status_code == 404
            assert (await c.get("/api/bridge/jobs/jobanna/gcode", headers=anna)).status_code == 401

            stats = (await c.get("/api/admin/stats", headers={"Authorization": "Bearer operator-token"})).json()
            assert stats["bridges"] == 1 and stats["bridges_online"] == 1

            # the same bridge connects again: the new socket wins
            ws2 = await websockets.connect(url, additional_headers=auth)
            await ws2.send(json.dumps({"type": "hello", "version": "0.24.0", "printers": []}))
            assert json.loads(await ws2.recv())["type"] == "welcome"
            await asyncio.wait_for(loop_task, 5)
            assert ws.close_code == 4000

            # rename, remove: the socket is closed and the token is dead
            r = await c.patch(f"/api/bridges/{bid}", json={"name": "Keller"}, headers=anna)
            assert r.json()["name"] == "Keller"
            assert (await c.delete(f"/api/bridges/{bid}", headers=ben)).status_code == 404
            assert (await c.delete(f"/api/bridges/{bid}", headers=anna)).status_code == 200
            assert await _closed(ws2) == 4001
            assert (await c.get("/api/bridge/jobs/jobanna/gcode", headers=auth)).status_code == 401
            assert (await c.get("/api/bridges", headers=anna)).json() == []
            assert api.HUB.count() == 0

    asyncio.run(run())


def test_bridges_only_in_the_cloud(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    api = importlib.reload(importlib.import_module("printshare.api"))
    with TestClient(api.app) as c:
        assert c.post("/api/bridge/pair/start", json={"bridge_id": str(uuid.uuid4())}).status_code == 404
        assert c.get("/api/bridges", headers={"Authorization": "Bearer t"}).json() == []
        with c.websocket_connect("/api/bridge/ws", headers={"Authorization": "Bearer pp3db_x"}) as ws:
            with pytest.raises(Exception):
                ws.receive_text()
