"""Bridge mode of a home server (docs/BRIDGE.md step 3): sealed secrets, added printers, and the whole path
app → cloud → WebSocket → bridge (a separate server process) → printer."""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from fastapi import Body, Depends

from printshare.bridge import registry, seal
from .fakes import FakeMoonraker, FakeOctoPrint
from .test_cloud import CC, cloud  # noqa: F401 - fixture

ROOT = Path(__file__).resolve().parents[1]
MK4S = "Prusa MK4S 0.4 nozzle"


# ---------- sealed secrets ----------
def test_seal_roundtrip_and_tampering():
    priv, pub = seal.keypair()
    blob = seal.seal(pub, {"address": "192.168.1.50", "password": "geheim"})
    assert seal.unseal(priv, blob) == {"address": "192.168.1.50", "password": "geheim"}
    assert seal.seal(pub, {"a": 1}) != seal.seal(pub, {"a": 1}), "a new key for every message"
    other_priv, _ = seal.keypair()
    with pytest.raises(seal.SealError):
        seal.unseal(other_priv, blob)                         # sealed for another bridge
    raw = bytearray(__import__("base64").b64decode(blob))
    raw[-1] ^= 1
    with pytest.raises(seal.SealError):
        seal.unseal(priv, __import__("base64").b64encode(bytes(raw)).decode())
    with pytest.raises(seal.SealError):
        seal.unseal(priv, "not base64 !")


def test_registry_build():
    cc = registry.build({"type": "elegoo_sdcp", "name": "Werkstatt"}, {"address": "http://192.168.1.5:3030/x"}, "werkstatt")
    assert cc == {"id": "werkstatt", "type": "elegoo_sdcp", "name": "Werkstatt", "host": "192.168.1.5"}
    k = registry.build({"type": "moonraker", "cosmos": True}, {"address": "192.168.1.6"}, "k")
    assert k["url"] == "http://192.168.1.6" and k["slicing"] == {"machine_preset": "cosmos"}
    pl = registry.build({"type": "prusalink", "machine": MK4S}, {"address": "10.0.0.9", "password": "pw"}, "p")
    assert pl["password"] == "pw" and pl["slicing"] == {"machine": MK4S}
    # update without a new address/password keeps the old ones
    upd = registry.build({"name": "MK4S"}, {}, "p", old=pl)
    assert upd["url"] == "http://10.0.0.9" and upd["password"] == "pw" and upd["name"] == "MK4S"
    for fields, secrets in (({"type": "bambu"}, {"address": "1.2.3.4"}), ({"type": "moonraker"}, {}),
                            ({"type": "moonraker"}, {"address": "1.2.3.4; rm -rf /"})):
        with pytest.raises(ValueError):
            registry.build(fields, secrets, "x")
    assert registry.slug("Centauri Carbon", {"centauri-carbon"}) == "centauri-carbon-2"


# ---------- end to end ----------
def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def cloud_live(cloud):  # noqa: F811
    """The cloud in this process (uvicorn thread) + a test route that sends any method to a bridge."""
    api = cloud

    @api.app.post("/test/bridge/{bridge_id}/{method}")
    async def _call(bridge_id: str, method: str, params: dict = Body(default={}), acct=Depends(api.auth)):
        try:
            return {"result": await api.HUB.call(bridge_id, acct.id, method, params, 30)}
        except api.BridgeError as e:
            return {"error": e.code, "message": str(e)}

    port = _port()
    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    yield api, port
    server.should_exit = True
    thread.join(5)


def _orca_profiles(root: Path) -> None:
    for vendor, kinds in {
        "Elegoo": {"machine": [{"name": CC}], "process": [{"name": "0.20mm Standard @Elegoo CC 0.4 nozzle", "compatible_printers": [CC]}],
                   "filament": [{"name": "Elegoo PLA @ECC", "compatible_printers": [CC]}]},
        "Prusa": {"machine": [{"name": MK4S, "default_print_profile": "0.20mm SPEED @Prusa MK4S 0.4",
                               "default_filament_profile": "Prusament PLA @PG"}],
                  "process": [{"name": "0.20mm SPEED @Prusa MK4S 0.4", "compatible_printers": [MK4S]}],
                  "filament": [{"name": "Prusament PLA @PG", "compatible_printers": [MK4S]}]},
    }.items():
        for kind, presets in kinds.items():
            (root / vendor / kind).mkdir(parents=True, exist_ok=True)
            for p in presets:
                (root / vendor / kind / f"{p['name']}.json").write_text(json.dumps(p))


async def _until(fn, timeout=20.0, step=0.2):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = await fn()
        if last:
            return last
        await asyncio.sleep(step)
    raise AssertionError(f"timed out, last: {last}")


def test_bridge_end_to_end(cloud_live, tmp_path):
    api, cloud_port = cloud_live
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    _orca_profiles(home / "orca")
    mr_port, octo_port, home_port = _port(), _port(), _port()
    cfg = home / "config" / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "api_token": "hometoken", "work_dir": str(home / "work"), "gcode_dir": str(home / "gcode"),
        "orca_profiles_dir": str(home / "orca"), "bridge": True, "bridge_url": f"http://127.0.0.1:{cloud_port}",
        "lan_subnet": "127.0.0.0/30",
        "printers": [{"id": "voron", "type": "moonraker", "name": "Voron", "url": f"http://127.0.0.1:{mr_port}"}]}))
    env = {**os.environ, "PRINTSHARE_CONFIG": str(cfg), "PYTHONPATH": str(ROOT)}
    for k in ("PRINTSHARE_CLOUD", "PRINTSHARE_BRIDGE", "PRINTSHARE_BRIDGE_URL"):
        env.pop(k, None)
    log = (tmp_path / "home.log").open("w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "printshare.api:app", "--host", "127.0.0.1",
                             "--port", str(home_port), "--log-level", "info"], env=env, stdout=log, stderr=subprocess.STDOUT)
    home_url, H = f"http://127.0.0.1:{home_port}", {"Authorization": "Bearer hometoken"}

    async def run():
        voron, octo = FakeMoonraker(port=mr_port), FakeOctoPrint(port=octo_port)
        await voron.start()
        await octo.start()
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                cl = f"http://127.0.0.1:{cloud_port}"

                async def home_state():
                    try:
                        return (await c.get(f"{home_url}/api/bridge", headers=H)).json()
                    except httpx.HTTPError:
                        return None

                # the home server asks the cloud for a pairing code and shows it
                st = await _until(lambda: _with(home_state(), lambda s: s and s.get("code") and s))
                assert st["state"] == "pairing" and st["enabled"] and not st["paired"]
                assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", st["code"])
                assert stat.S_IMODE((home / "config" / "bridge.yaml").stat().st_mode) == 0o600

                # Anna enters it in the app
                assert (await c.post(f"{cl}/api/auth/code", json={"email": "anna@example.com"})).status_code == 200
                code = re.search(r"\d{6}", api.MAILER.sent[-1][1]).group()
                anna = {"Authorization": "Bearer " + (await c.post(f"{cl}/api/auth/login", json={
                    "email": "anna@example.com", "code": code})).json()["token"]}
                assert (await c.post(f"{cl}/api/bridges/pair", json={"code": st["code"]}, headers=anna)).status_code == 200

                async def online():
                    b = (await c.get(f"{cl}/api/bridges", headers=anna)).json()
                    return b[0] if b and b[0]["online"] else None
                bridge = await _until(online)
                assert [p["id"] for p in bridge["printers"]] == ["voron"] and bridge["version"] == api.app.version
                st = await home_state()
                assert st["state"] == "connected" and st["account"] == "anna@example.com" and st["code"] is None

                async def call(method, params=None):
                    return (await c.post(f"{cl}/test/bridge/{bridge['id']}/{method}", json=params or {},
                                         headers=anna)).json()

                # status and controls run the home server's own functions against the printer
                r = await call("printer.status", {"printer": "voron"})
                assert r["result"]["state"] == "printing" and r["result"]["kind"] == "active"
                assert (await call("printer.status", {"printer": "nope"}))["error"] == "unknown_printer"
                assert (await call("printer.control", {"printer": "voron", "action": "pause"}))["result"]["ok"]
                assert voron.actions == ["pause"]
                assert (await call("printer.control", {"printer": "voron", "action": "cancel"}))["error"] == "confirm_required"
                assert (await call("printers.list"))["result"][0]["capabilities"]["removable"] is False

                # job.send: the bridge fetches Anna's G-code from the cloud and starts it at home
                g = tmp_path / "cube.gcode"
                g.write_text(";LAYER_CHANGE\nG1 X1 Y1\n")
                uid = api.ACCOUNTS.user_for_token(anna["Authorization"][7:]).id
                api.JOBS["j1"] = {"id": "j1", "owner": uid, "state": "sliced", "created": time.time(),
                                  "result": {"gcode": str(g), "source_file": "cube.stl", "printer": "voron"}}
                r = await call("job.send", {"printer": "voron", "job": "j1", "start": True})
                assert r["error"] == "confirm_required"
                r = await call("job.send", {"printer": "voron", "job": "j1", "start": True, "confirm": True})
                assert r["error"] == "busy", "the printer is still printing"
                voron.state = "standby"
                r = await call("job.send", {"printer": "voron", "job": "j1", "start": True, "confirm": True})
                assert r["result"]["state"] == "started" and r["result"]["file"] == "cube.gcode", r
                assert voron.uploads[-1]["data"] == g.read_bytes() and voron.uploads[-1]["print"] == "true"
                assert (await call("job.send", {"printer": "voron", "job": "unknown"}))["error"] == "download_failed"

                # add a printer from the app: address + API key sealed for this bridge, the cloud only passes it on
                sealed = seal.seal(bridge["public_key"], {"address": f"127.0.0.1:{octo_port}", "api_key": "OCTOKEY"})
                r = await call("printer.add", {"printer": {"name": "Octo Pi", "type": "octoprint", "machine": MK4S},
                                               "sealed": sealed})
                assert r["result"]["id"] == "octo-pi" and r["result"]["capabilities"]["removable"], r
                added = home / "config" / "printers-added.yaml"
                assert stat.S_IMODE(added.stat().st_mode) == 0o600 and "OCTOKEY" in added.read_text()
                ids = await _until(lambda: _with(c.get(f"{cl}/api/bridges", headers=anna),
                                                 lambda r: [p["id"] for p in r.json()[0]["printers"]] == ["voron", "octo-pi"] and r.json()[0]["printers"]))
                assert "OCTOKEY" not in json.dumps(ids) and str(octo_port) not in json.dumps(ids)
                assert (await call("printer.status", {"printer": "octo-pi"}))["result"]["kind"] in ("idle", "active")
                bad = seal.seal(seal.keypair()[1], {"address": "1.2.3.4"})
                assert (await call("printer.add", {"printer": {"type": "octoprint"}, "sealed": bad}))["error"] == "invalid"
                assert (await call("printer.remove", {"printer": "voron"}))["error"] == "invalid"
                assert (await call("printer.remove", {"printer": "octo-pi"}))["result"] == {"removed": "octo-pi"}
                assert [p["id"] for p in (await call("printers.list"))["result"]] == ["voron"]
                assert isinstance((await call("discover"))["result"], list)

                # ---- step 4: the app's own endpoints, forwarded by the cloud ----
                api_ = f"{cl}/api"
                printers = (await c.get(f"{api_}/printers", headers=anna)).json()
                assert [(p["id"], p["bridge"]) for p in printers] == [("voron", bridge["id"])]
                voron.state = "printing"
                r = await c.get(f"{api_}/printers/voron/status", headers=anna)
                assert r.status_code == 200 and r.json()["kind"] == "active"
                r = await c.post(f"{api_}/printers/voron/control", json={"action": "resume"}, headers=anna)
                assert r.status_code == 200 and voron.actions[-1] == "resume"
                r = await c.post(f"{api_}/printers/voron/control", json={"action": "cancel"}, headers=anna)
                assert r.status_code == 409 and "confirm" in r.json()["detail"]
                assert (await c.get(f"{api_}/printers/voron/controls", headers=anna)).json()["heaters"]
                assert (await c.get(f"{api_}/printers/voron/temperatures", headers=anna)).status_code == 200
                cam = (await c.get(f"{api_}/printers/voron/camera", headers=anna)).json()
                assert cam["available"] and cam["snapshot"] and cam["stream"] is False
                r = await c.get(f"{api_}/printers/voron/camera/snapshot?w=320", headers=anna)
                assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
                assert (await c.get(f"{api_}/printers/voron/power", headers=anna)).json()["available"] is False
                # the normal send endpoint: the job goes through the bridge, its upload steps land in the job log
                voron.state = "standby"
                api.JOBS["j2"] = {"id": "j2", "owner": uid, "state": "sliced", "created": time.time(), "log": [],
                                  "error": None, "kind": "prepare", "request": {},
                                  "result": {"printer": "voron", "source_file": "cube.stl", "gcode": str(g),
                                             "print_time": "1m", "filament_g": 1.0, "filament_m": 0.3}}
                r = await c.post(f"{api_}/jobs/j2/send", json={"start": True}, headers=anna)
                assert r.status_code == 400, "the cloud asks for the confirmation itself"
                r = await c.post(f"{api_}/jobs/j2/send", json={"start": True, "confirm": True}, headers=anna)
                assert r.status_code == 200
                job = await _until(lambda: _with(c.get(f"{api_}/jobs/j2", headers=anna),
                                                 lambda r: r.json()["state"] != "sending" and r.json()))
                assert job["state"] == "started" and not job["error"], job
                assert job["printer_file"] == "cube.gcode", "the name on the printer, for spool bookings"
                assert job["log"], "upload steps from the bridge"
                assert len(voron.uploads) == 2
                # rename in the app: stays when the bridge reports its printers again
                r = await c.patch(f"{api_}/printers/voron", json={"name": "Mein Voron"}, headers=anna)
                assert r.status_code == 200 and r.json()["name"] == "Mein Voron" and r.json()["bridge"] == bridge["id"]
                # discover + add through the bridge with the app's endpoints
                assert isinstance((await c.post(f"{api_}/bridges/{bridge['id']}/discover", headers=anna)).json(), list)
                sealed = seal.seal(bridge["public_key"], {"address": f"127.0.0.1:{octo_port}", "api_key": "OCTOKEY"})
                r = await c.post(f"{api_}/bridges/{bridge['id']}/printers", headers=anna, json={
                    "printer": {"name": "Octo Pi", "type": "octoprint", "machine": MK4S, "url": "http://evil"}, "sealed": sealed})
                assert r.status_code == 200, r.text
                assert r.json()["id"] == "octo-pi" and r.json()["machine"] == MK4S
                assert (await c.get(f"{api_}/printers/octo-pi/status", headers=anna)).json()["kind"] in ("idle", "active")
                names = {p["id"]: p["name"] for p in (await c.get(f"{api_}/printers", headers=anna)).json()}
                assert names == {"voron": "Mein Voron", "octo-pi": "Octo Pi"}
                assert "octo_port" not in json.dumps(api.ACCOUNTS.printers(uid)) and "OCTOKEY" not in json.dumps(api.ACCOUNTS.printers(uid))
                assert str(octo_port) not in json.dumps(api.ACCOUNTS.printers(uid)), "addresses never reach the cloud"
                # new key for the OctoPrint printer, sealed again
                new = seal.seal(bridge["public_key"], {"api_key": "OCTOKEY2"})
                assert (await c.put(f"{api_}/printers/octo-pi/bridge-access", json={"sealed": new}, headers=anna)).status_code == 200
                assert "OCTOKEY2" in (home / "config" / "printers-added.yaml").read_text()
                # remove: only what was added through the app
                r = await c.delete(f"{api_}/printers/voron", headers=anna)
                assert r.status_code == 400 and "server" in r.json()["detail"]
                assert (await c.delete(f"{api_}/printers/octo-pi", headers=anna)).status_code == 200
                assert [p["id"] for p in (await c.get(f"{api_}/printers", headers=anna)).json()] == ["voron"]
                assert "octo-pi" not in (home / "config" / "printers-added.yaml").read_text()

                # removed from the app: the bridge forgets its token and shows a new code
                assert (await c.delete(f"{cl}/api/bridges/{bridge['id']}", headers=anna)).status_code == 200
                assert (await c.get(f"{cl}/api/printers", headers=anna)).json() == [], "its printers go with it"
                st = await _until(lambda: _with(home_state(), lambda s: s and s.get("code") and s))
                assert st["state"] == "pairing" and not st["paired"]

                # switched off on the home server
                assert (await c.post(f"{home_url}/api/bridge", json={"enabled": False}, headers=H)).json()["state"] == "off"
        finally:
            await voron.stop()
            await octo.stop()

    try:
        asyncio.run(run())
    finally:
        proc.terminate()
        proc.wait(10)
        log.close()
    assert "Traceback" not in (tmp_path / "home.log").read_text(), (tmp_path / "home.log").read_text()[-3000:]


async def _with(awaitable, check):
    try:
        return check(await awaitable)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None
