"""Smart plug through Home Assistant (issue #9): adapter, settings on the web page, API safety."""
import asyncio
import os
import stat

import pytest
from fastapi.testclient import TestClient

from printshare import power as plug

from .fakes import FakeHomeAssistant, FakeMoonraker
from .test_api import H, BackgroundFake, api  # noqa: F401 - module fixture

HA = "http://127.0.0.1:8123"


def run(coro):
    return asyncio.run(coro)


def test_adapter_against_fake_home_assistant():
    async def go():
        ha = FakeHomeAssistant()
        await ha.start()
        try:
            p = plug.get_power(plug.PowerConfig(url=HA + "/", token="ha-token", entity="switch.drucker"))
            assert await p.state() == "off"
            await p.turn(True)
            assert await p.state() == "on" and ha.calls == [("turn_on", "switch.drucker")]
            assert (await p.test()) == {"state": "on", "name": "Drucker-Steckdose"}
            ents = await p.entities()
            assert [e["entity"] for e in ents] == ["switch.drucker", "switch.kaputt", "light.werkstatt"]  # no sensors
            broken = plug.get_power(plug.PowerConfig(url=HA, token="ha-token", entity="switch.kaputt"))
            assert await broken.state() == "unavailable"
            for cfg, msg in [(plug.PowerConfig(url=HA, token="wrong", entity="switch.drucker"), "401"),
                             (plug.PowerConfig(url=HA, token="ha-token", entity="switch.nope"), "no entity"),
                             (plug.PowerConfig(url="http://127.0.0.1:1", token="x", entity="switch.drucker"), "not reachable"),
                             (plug.PowerConfig(url=HA, token="ha-token", entity="sensor.temp"), "entity must be"),
                             (plug.PowerConfig(url=HA, token="ha-token", entity="switch.a/../../x"), "entity must be")]:
                with pytest.raises(plug.PowerError, match=msg):
                    await plug.get_power(cfg).state()
        finally:
            await ha.stop()
    run(go())
    with pytest.raises(plug.PowerError, match="address"):
        plug.get_power(plug.PowerConfig(url="192.168.1.5", token="x", entity="switch.a"))


def test_supervisor_mode_needs_no_url_or_token(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup")
    p = plug.get_power(plug.PowerConfig(entity="switch.drucker"))
    assert p.base == plug.SUPERVISOR_URL and p.headers == {"Authorization": "Bearer sup"}
    assert plug.PowerConfig(entity="switch.drucker").public()["supervisor"] is True
    monkeypatch.delenv("SUPERVISOR_TOKEN")
    with pytest.raises(plug.PowerError, match="address"):
        plug.get_power(plug.PowerConfig(entity="switch.drucker"))


def test_power_settings_and_switching_through_the_api(api, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(api.settings, "config_dir", str(tmp_path))
    with TestClient(api.app) as c, BackgroundFake(FakeHomeAssistant()) as ha, BackgroundFake(FakeMoonraker()) as moon:
        base = "/api/printers/dom/power"
        assert c.get(base, headers=H).json() == {"available": False, "state": None}
        assert c.get("/api/printers", headers=H).json()[0]["power"] is False
        assert c.post(base, headers=H, json={"on": True}).status_code == 404
        # web page: test + entity list before saving, then save
        body = {"url": HA, "token": "ha-token", "entity": "switch.drucker"}
        assert c.post(base + "/test", headers=H, json=body).json() == {"ok": True, "state": "off", "name": "Drucker-Steckdose"}
        assert c.post(base + "/test", headers=H, json={**body, "token": "bad"}).json()["ok"] is False
        assert "switch.drucker" in [e["entity"] for e in c.post(base + "/entities", headers=H, json=body).json()]
        assert c.put(base + "/config", headers=H, json={**body, "entity": "sensor.temp"}).status_code == 400
        saved = c.put(base + "/config", headers=H, json=body).json()
        assert saved["configured"] and saved["token_set"] and "token" not in saved and saved["entity"] == "switch.drucker"
        f = tmp_path / "printers.d" / "dom.yaml"
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600          # holds the HA token
        assert "ha-token" not in c.get(base + "/config", headers=H).text
        # later edits without a token keep the stored one
        c.put(base + "/config", headers=H, json={"url": HA, "entity": "switch.drucker"})
        assert c.post(base + "/test", headers=H, json={"url": HA, "entity": "switch.drucker"}).json()["ok"]
        assert c.get("/api/printers", headers=H).json()[0]["power"] is True
        # switching
        assert c.post(base, headers=H, json={"on": True}).json() == {"ok": True, "state": "on"}
        assert c.get(base, headers=H).json() == {"available": True, "state": "on", "error": None}
        # never switch off during a print (the server checks, not only the app)
        moon.state = "printing"
        r = c.post(base, headers=H, json={"on": False})
        assert r.status_code == 409 and ha.states["switch.drucker"] == "on"
        moon.state = "standby"
        assert c.post(base, headers=H, json={"on": False}).json()["state"] == "off"
        assert ha.calls == [("turn_on", "switch.drucker"), ("turn_off", "switch.drucker")]
        # Home Assistant down: a clear message, not a crash
        c.put(base + "/config", headers=H, json={"url": "http://127.0.0.1:1", "entity": "switch.drucker"})
        st = c.get(base, headers=H).json()
        assert st["state"] == "unknown" and "not reachable" in st["error"]
        assert c.post(base, headers=H, json={"on": True}).status_code == 502
        # remove
        assert c.delete(base + "/config", headers=H).json()["configured"] is False
        assert not f.exists()
