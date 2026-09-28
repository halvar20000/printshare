"""PrusaLink and OctoPrint adapters against fake servers built from the official API docs."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from printshare.bootstrap import ensure_config
from printshare.config import PrinterConfig, load_settings
from printshare.printers import get_adapter
from printshare.printers.octoprint import OctoPrintError
from printshare.printers.prusalink import PrusaLinkError, remote_name

from .fakes import FakeOctoPrint, FakePrusaLink

NO_HA = Path("/nonexistent/options.json")


def run(fake, fn):
    async def go():
        await fake.start()
        try:
            return await fn()
        finally:
            await fake.stop()
    return asyncio.run(go())


def gcode(tmp_path: Path, name: str = "My Part (v2).gcode") -> Path:
    g = tmp_path / name
    g.write_text("M862.3 P \"MK4S\"\nG1 X1\n")
    return g


# ---------- PrusaLink ----------
def prusa(fake: FakePrusaLink, **kw) -> PrinterConfig:
    return PrinterConfig(id="mk4", type="prusalink", url=f"127.0.0.1:{fake.port}", **kw)


def test_prusalink_upload_start_status_control(tmp_path):
    fake = FakePrusaLink()
    ad = get_adapter(prusa(fake, password="secret"))

    async def flow():
        idle = await ad.status()
        sent = await ad.send(gcode(tmp_path), start=True)
        st = await ad.status()
        await ad.control("pause")
        paused = await ad.status()
        await ad.control("resume")
        await ad.control("cancel")
        return idle, sent, st, paused, await ad.status()

    idle, sent, st, paused, stopped = run(fake, flow)
    assert idle["state"] == "standby" and idle["nozzle"] == 214.9
    assert sent == {"uploaded": "usb/My_Part_v2.gcode", "started": True}
    assert fake.files["usb/My_Part_v2.gcode"].startswith(b"M862.3")
    assert (st["state"], st["file"], st["progress"], st["time_remaining_s"]) == ("printing", "My_Part_v2.gcode", 12.0, 440)
    assert paused["state"] == "paused"
    assert fake.actions == ["pause", "resume", "stop"] and stopped["state"] == "cancelled"


def test_prusalink_upload_only_and_api_key(tmp_path):
    fake = FakePrusaLink(api_key="KEY123")
    ad = get_adapter(prusa(fake, api_key="KEY123"))
    sent = run(fake, lambda: ad.send(gcode(tmp_path, "cube.gcode"), start=False))
    assert sent["started"] is False and fake.state == "IDLE" and "usb/cube.gcode" in fake.files


@pytest.mark.parametrize("cfg,fake_kw,match", [
    ({"password": "wrong"}, {}, "rejected the password"),
    ({"password": "secret"}, {"usb": False}, "USB drive"),
])
def test_prusalink_errors(tmp_path, cfg, fake_kw, match):
    fake = FakePrusaLink(**fake_kw)
    ad = get_adapter(prusa(fake, **cfg))
    with pytest.raises(PrusaLinkError, match=match):
        run(fake, lambda: ad.send(gcode(tmp_path), start=True))


def test_prusalink_needs_credentials():
    with pytest.raises(ValueError, match="password"):
        get_adapter(PrinterConfig(id="x", type="prusalink", url="http://1.2.3.4"))
    assert remote_name(Path("ÄÖ weird name!!.GCODE")) == "weird_name.gcode"


# ---------- OctoPrint ----------
def octo(fake: FakeOctoPrint, key: str = "OCTOKEY") -> PrinterConfig:
    return PrinterConfig(id="ender", type="octoprint", url=f"http://127.0.0.1:{fake.port}/", api_key=key)


def test_octoprint_upload_start_status_control(tmp_path):
    fake = FakeOctoPrint()
    ad = get_adapter(octo(fake))

    async def flow():
        idle = await ad.status()
        sent = await ad.send(gcode(tmp_path, "benchy.gcode"), start=True)
        st = await ad.status()
        await ad.control("pause")
        paused = await ad.status()
        await ad.control("resume")
        await ad.control("cancel")
        return idle, sent, st, paused

    idle, sent, st, paused = run(fake, flow)
    assert idle["state"] == "standby" and idle["bed"] == 60.1
    assert sent == {"uploaded": "benchy.gcode", "started": True}
    assert fake.uploads[0]["print"] == "true" and fake.uploads[0]["data"].startswith(b"M862")
    assert (st["state"], st["file"], st["progress"]) == ("printing", "benchy.gcode", 33.3)
    assert paused["state"] == "paused"
    assert [c.get("action", c["command"]) for c in fake.commands] == ["pause", "resume", "cancel"]


def test_octoprint_printer_not_connected(tmp_path):
    fake = FakeOctoPrint(connected=False)
    ad = get_adapter(octo(fake))

    async def flow():
        st = await ad.status()
        try:
            await ad.send(gcode(tmp_path, "a.gcode"), start=True)
        except OctoPrintError as e:
            return st, e
        return st, None

    st, err = run(fake, flow)
    assert st["state"] == "offline" and st["nozzle"] is None
    assert err is not None and "did not start" in str(err)
    assert fake.uploads[0]["name"] == "a.gcode"  # the file is stored anyway


def test_octoprint_wrong_key(tmp_path):
    fake = FakeOctoPrint()
    ad = get_adapter(octo(fake, key="nope"))
    with pytest.raises(OctoPrintError, match="API key"):
        run(fake, ad.status)
    with pytest.raises(ValueError, match="api_key"):
        get_adapter(PrinterConfig(id="x", type="octoprint", url="http://1.2.3.4"))


# ---------- presets: never the Centauri profile for another printer ----------
@pytest.fixture
def profiles(tmp_path):
    """Minimal OrcaSlicer profile tree: a Prusa machine preset with its own defaults."""
    base = tmp_path / "profiles" / "Prusa" / "machine"
    base.mkdir(parents=True)
    (base / "common.json").write_text(json.dumps({
        "name": "fdm_machine_common_mk4s", "instantiation": "false",
        "default_filament_profile": ["Prusa Generic PLA @MK4S"], "host_type": "prusalink"}))
    (base / "mk4s.json").write_text(json.dumps({
        "name": "Prusa MK4S 0.4 nozzle", "inherits": "fdm_machine_common_mk4s",
        "default_print_profile": "0.20mm SPEED @MK4S 0.4"}))
    return tmp_path / "profiles"


def seed(cfg: Path, profiles: Path) -> None:
    cfg.write_text(f"work_dir: {cfg.parent / 'w'}\ngcode_dir: {cfg.parent / 'g'}\norca_profiles_dir: {profiles}\n")


def test_machine_defaults_from_orca_preset(tmp_path, profiles):
    cfg = tmp_path / "config.yaml"
    seed(cfg, profiles)
    env = {"PRINTER_TYPE": "prusalink", "PRINTER_ADDRESS": "192.168.1.70", "PRINTER_NAME": "MK4S",
           "PRINTER_PASSWORD": "pw", "PRINTER_PROFILE": "Prusa MK4S 0.4 nozzle"}
    ensure_config(cfg, env, NO_HA)
    p = load_settings(cfg).printers[0]
    assert (p.type, p.url, p.password, p.username) == ("prusalink", "http://192.168.1.70", "pw", "maker")
    assert p.slicing.machine == "Prusa MK4S 0.4 nozzle"
    assert p.slicing.process == "0.20mm SPEED @MK4S 0.4"
    assert p.slicing.filament == "Prusa Generic PLA @MK4S"
    assert p.slicing.machine_preset is None


@pytest.mark.parametrize("env,match", [
    ({"PRINTER_TYPE": "prusalink", "PRINTER_PASSWORD": "pw"}, "printer_profile is required"),
    ({"PRINTER_TYPE": "prusalink", "PRINTER_PASSWORD": "pw", "PRINTER_PROFILE": "Elegoo Centauri Carbon 0.4 nozzle"},
     "printer_profile is required"),
    ({"PRINTER_TYPE": "prusalink", "PRINTER_PROFILE": "Prusa MK4S 0.4 nozzle"}, "password"),
    ({"PRINTER_TYPE": "octoprint", "PRINTER_PROFILE": "Prusa MK4S 0.4 nozzle"}, "API key"),
])
def test_setup_form_guards(tmp_path, env, match):
    with pytest.raises(ValueError, match=match):
        ensure_config(tmp_path / "config.yaml", {"PRINTER_ADDRESS": "1.2.3.4", **env}, NO_HA)


def test_unknown_machine_is_a_clear_error(tmp_path, profiles):
    cfg = tmp_path / "config.yaml"
    seed(cfg, profiles)
    cfg.write_text(cfg.read_text() + "printers:\n  - id: x\n    type: octoprint\n    url: http://a\n"
                   "    api_key: k\n    slicing:\n      machine: Nope 3000\n")
    with pytest.raises(ValueError, match="Printer x"):
        load_settings(cfg)
