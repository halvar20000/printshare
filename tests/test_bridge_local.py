"""Ready-made bridge (Raspberry Pi image): found by the app on the Wi-Fi, pairing code only for the home network."""
from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def bridge_api(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(cfg))
    monkeypatch.setenv("PRINTSHARE_BRIDGE", "1")
    monkeypatch.setenv("PRINTSHARE_BRIDGE_ONLY", "1")
    monkeypatch.setenv("PRINTSHARE_NAME", "pocketprint3d")
    api = importlib.reload(importlib.import_module("printshare.api"))
    # no lifespan (no connection to the cloud): the client is put into the pairing state by hand
    bc = api.BRIDGE_CLIENT
    bc.state, bc.code, bc.code_expires = "pairing", "K7Q4-M2ZX", time.time() + 600
    yield api
    monkeypatch.delenv("PRINTSHARE_BRIDGE_ONLY")
    importlib.reload(api)


def _client(api, ip="192.168.1.23", host="192.168.1.50"):
    return TestClient(api.app, client=(ip, 50000), base_url=f"http://{host}")


def test_hello_and_local_code(bridge_api):
    c = _client(bridge_api)
    hello = c.get("/api/bridge/hello").json()
    assert hello["pocketprint3d"] == "bridge" and hello["pairable"] and not hello["paired"]
    assert hello["name"] == "PocketPrint3D (pocketprint3d)" and hello["version"] == bridge_api.app.version
    r = c.get("/api/bridge/local-code")
    assert r.status_code == 200 and r.json()["code"] == "K7Q4-M2ZX" and r.json()["expires_in"] > 500
    assert "access-control-allow-origin" not in r.headers
    for host in ("localhost:80", "pocketprint3d.local", "[fd00::5]:8484"):
        assert _client(bridge_api, host=host).get("/api/bridge/local-code").status_code == 200, host
    # the status page shows it too, and / is the status page on a bridge-only install
    assert "K7Q4-M2ZX" in c.get("/bridge").text
    assert "K7Q4-M2ZX" in c.get("/", headers={"Accept-Language": "de-DE"}).text


def test_local_code_refused(bridge_api):
    api = bridge_api
    assert _client(api, ip="8.8.8.8").get("/api/bridge/local-code").status_code == 403          # internet
    assert _client(api, host="evil.example").get("/api/bridge/local-code").status_code == 403       # DNS rebinding
    assert _client(api).get("/api/bridge/local-code", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403
    page = _client(api, host="evil.example").get("/bridge").text
    assert "K7Q4-M2ZX" not in page and "pocketprint3d.local" in page
    # paired: no code any more, the account only masked
    from printshare.bridge.client import load_state, save_state
    st = load_state(api.settings)
    st.update(token="pp3db_x", account="thomas@example.org")
    save_state(api.settings, st)
    api.BRIDGE_CLIENT.state = "connected"
    c = _client(api)
    assert c.get("/api/bridge/local-code").status_code == 409
    hello = c.get("/api/bridge/hello").json()
    assert hello["paired"] and not hello["pairable"] and hello["account"] == "t***@example.org"
    assert "t***@example.org" in c.get("/bridge").text and "thomas@" not in c.get("/bridge").text


def test_full_server_never_hands_out_the_code(bridge_api, monkeypatch):
    api = bridge_api
    api.settings.bridge_only = False             # Unraid / Home Assistant with bridge mode on: code only with the token
    c = _client(api)
    assert c.get("/api/bridge/local-code").status_code == 403
    assert c.get("/api/bridge/hello").json()["pairable"] is False
    assert "K7Q4-M2ZX" not in c.get("/bridge").text
