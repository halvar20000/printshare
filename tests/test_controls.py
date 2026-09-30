"""Printer control: temperatures, fans, light, speed, temperature history (issue #5)."""
from __future__ import annotations

import asyncio

from printshare.config import PrinterConfig
from printshare.printers import get_adapter

from .fakes import FakeCentauri, FakeMoonraker, FakeOctoPrint
from .test_api import H, BackgroundFake, api, client  # noqa: F401 (fixtures)


def run(fake, fn):
    async def go():
        await fake.start()
        try:
            return await fn()
        finally:
            await fake.stop()
    return asyncio.run(go())


MOON = PrinterConfig(id="d", type="moonraker", url="http://127.0.0.1:7125")


def test_moonraker_controls_status_and_commands():
    fake = FakeMoonraker()
    ad = get_adapter(MOON)

    async def go():
        caps = await ad.controls()
        st = await ad.status()
        for kind, target, value in (("heater", "nozzle", 210), ("heater", "bed", 60), ("fan", "part", 50),
                                    ("fan", "part", 0), ("fan", "aux_fan", 30), ("light", "case", False),
                                    ("speed", "", 120)):
            await ad.adjust(kind, target, value)
        return caps, st, await ad.temperature_history()
    caps, st, hist = run(fake, go)
    assert caps["heaters"] == [{"id": "nozzle", "max": 320.0}, {"id": "bed", "max": 110.0}]   # from the Klipper config
    assert [f["id"] for f in caps["fans"]] == ["part", "aux_fan"] and caps["lights"] == [{"id": "case"}]
    assert st["fans"] == {"part": 50, "aux_fan": 0} and st["lights"] == {"case": True} and st["speed"] == 100
    assert st["heaters"]["chamber"] == {"actual": 31.5, "target": None}      # sensor only: shown, not settable
    assert fake.scripts == ["SET_HEATER_TEMPERATURE HEATER=extruder TARGET=210",
                            "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=60",
                            "M106 S128", "M107", "SET_FAN_SPEED FAN=aux_fan SPEED=0.3",
                            "SET_LED LED=case RED=0 GREEN=0 BLUE=0 WHITE=0", "M220 S120"]
    assert len(hist["nozzle"]) == 120 and hist["nozzle"][-1][0] == 0 and hist["nozzle"][-1][2] == 200.0
    assert hist["nozzle"][0][0] < -1100 and "chamber" in hist


def test_centauri_controls():
    fake = FakeCentauri()
    ad = get_adapter(PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1", mainboard_id="FAKECC0001"))

    async def go():
        for kind, target, value in (("heater", "nozzle", 200), ("heater", "chamber", 40), ("fan", "part", 40),
                                    ("fan", "chamber", 100), ("light", "light", False), ("speed", "", 130)):
            await ad.adjust(kind, target, value)
        return await ad.status(), await ad.controls()
    st, caps = run(fake, go)
    assert fake.params == [{"TempTargetNozzle": 200.0}, {"TempTargetBox": 40.0},
                           {"TargetFanSpeed": {"ModelFan": 40}}, {"TargetFanSpeed": {"BoxFan": 100}},
                           {"LightStatus": {"SecondLight": 0}}, {"PrintSpeedPct": 130}]
    assert st["fans"] == {"part": 0, "aux": 0, "chamber": 0} and st["lights"] == {"light": True}
    assert st["heaters"]["chamber"]["actual"] == 23.1 and st["speed"] == 100
    assert caps["speed"] == {"modes": [50, 100, 130, 160]}


def test_octoprint_controls():
    fake = FakeOctoPrint()
    ad = get_adapter(PrinterConfig(id="o", type="octoprint", url=f"http://127.0.0.1:{fake.port}", api_key="OCTOKEY"))

    async def go():
        for kind, target, value in (("heater", "nozzle", 215), ("heater", "bed", 65), ("fan", "part", 100),
                                    ("speed", "", 90)):
            await ad.adjust(kind, target, value)
        return await ad.temperature_history()
    hist = run(fake, go)
    assert fake.posts == [("tool", {"command": "target", "targets": {"tool0": 215.0}}),
                          ("bed", {"command": "target", "target": 65.0}),
                          ("command", {"commands": ["M106 S255"]}), ("command", {"commands": ["M220 S90"]})]
    assert [p[1] for p in hist["nozzle"]] == [200.0, 214.8] and hist["bed"][-1][2] == 60.0


def test_adjust_api_limits_and_confirmation(api, client):
    with BackgroundFake(FakeMoonraker()) as fake:
        fake.state = "printing"
        post = lambda body: client.post("/api/printers/dom/adjust", headers=H, json=body)  # noqa: E731
        assert post({"kind": "heater", "id": "nozzle", "value": 400}).status_code == 400        # above max_temp
        assert post({"kind": "heater", "id": "chamber", "value": 40}).status_code == 400        # sensor, no heater
        assert post({"kind": "fan", "id": "nope", "value": 50}).status_code == 400
        assert post({"kind": "fan", "id": "part", "value": 150}).status_code == 400
        assert post({"kind": "speed", "value": 500}).status_code == 400
        # while printing: temperature changes and switching a fan off need a confirmation
        r = post({"kind": "heater", "id": "nozzle", "value": 215})
        assert r.status_code == 409 and "confirm" in r.json()["detail"]
        assert post({"kind": "fan", "id": "part", "value": 0}).status_code == 409
        assert post({"kind": "heater", "id": "nozzle", "value": 215, "confirm": True}).status_code == 200
        assert post({"kind": "fan", "id": "part", "value": 80}).status_code == 200              # harmless
        assert post({"kind": "light", "id": "case", "value": True}).status_code == 200
        assert post({"kind": "speed", "value": 110}).status_code == 200
        fake.state = "standby"
        assert post({"kind": "heater", "id": "bed", "value": 0}).status_code == 200            # idle: no question
        caps = client.get("/api/printers/dom/controls", headers=H).json()
        temps = client.get("/api/printers/dom/temperatures", headers=H).json()
    assert fake.scripts == ["SET_HEATER_TEMPERATURE HEATER=extruder TARGET=215", "M106 S204",
                            "SET_LED LED=case RED=1 GREEN=1 BLUE=1 WHITE=1", "M220 S110",
                            "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=0"]
    assert caps["history"] is True and temps["source"] == "printer" and len(temps["series"]["bed"]) == 120


def test_temperature_log_for_printers_without_history(api, client, monkeypatch):
    """Printers without their own history (Centauri): PocketPrint3D records what the status queries saw."""
    api.TEMP_LOG.clear()
    ticks = [1000.0, 1002.0, 1010.0, 1020.0]                     # 1002 is < 4 s after 1000: skipped
    monkeypatch.setattr(api.time, "time", lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])
    for actual in (20.0, 21.0, 25.0, 30.0):
        api._log_temperatures("dom", {"heaters": {"nozzle": {"actual": actual, "target": 200.0},
                                                  "chamber": {"actual": None, "target": None}}})
    # the fake printer is not running -> no history from the printer -> PocketPrint3D's own record
    r = client.get("/api/printers/dom/temperatures", headers=H).json()
    assert r["source"] == "printshare"
    assert r["series"] == {"nozzle": [[-20, 20.0, 200.0], [-10, 25.0, 200.0], [0, 30.0, 200.0]]}
