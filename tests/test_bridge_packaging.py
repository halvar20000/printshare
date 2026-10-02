"""Bridge packaging (docs/BRIDGE.md step 6): HA add-on options, `printshare bridge`, running without OrcaSlicer."""
from __future__ import annotations

import json

import yaml

from printshare import bootstrap
from printshare.bridge.client import default_name
from printshare.config import load_settings


def test_addon_options_switch_bridge_mode(tmp_path):
    opts = tmp_path / "options.json"
    env: dict[str, str] = {}
    bootstrap.apply_addon_options(env, opts)                      # no add-on: nothing happens
    assert env == {}
    opts.write_text(json.dumps({"printers": [], "cloud_bridge": True, "lan_subnet": " 192.168.1.0/24 "}))
    bootstrap.apply_addon_options(env, opts)
    assert env == {"PRINTSHARE_BRIDGE": "1", "PRINTSHARE_LAN_SUBNET": "192.168.1.0/24", "PRINTSHARE_NAME": "Home Assistant"}
    env = {"PRINTSHARE_NAME": "Keller"}
    opts.write_text(json.dumps({"cloud_bridge": False}))
    bootstrap.apply_addon_options(env, opts)
    assert env == {"PRINTSHARE_NAME": "Keller"}


def test_addon_schema_has_the_bridge_options():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "homeassistant" / "printshare"
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    assert cfg["options"]["cloud_bridge"] is False and cfg["schema"]["cloud_bridge"] == "bool?"
    for lang in ("de", "en"):
        tr = yaml.safe_load((root / "translations" / f"{lang}.yaml").read_text())
        assert {"cloud_bridge", "lan_subnet"} <= set(tr["configuration"])


def test_printers_load_without_orcaslicer(tmp_path, monkeypatch):
    """The bridge image has no OrcaSlicer profiles: a Prusa still loads (the cloud picks quality/material)."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"orca_profiles_dir": str(tmp_path / "missing"), "work_dir": str(tmp_path / "w"),
                                   "gcode_dir": str(tmp_path / "g"), "printers": [
                                       {"id": "mk4s", "type": "prusalink", "url": "http://10.0.0.5", "password": "x",
                                        "slicing": {"machine": "Prusa MK4S 0.4 nozzle"}}]}))
    s = load_settings(cfg)
    assert s.printers[0].slicing.machine == "Prusa MK4S 0.4 nozzle"


def test_cli_bridge_switches_bridge_mode_on(monkeypatch, tmp_path):
    import printshare.cli as cli
    calls = {}
    # an existing config with its own folders (else the defaults /data/work … - not writable for normal users, e.g. CI)
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"api_token": "t", "work_dir": str(tmp_path / "w"),
                                                          "gcode_dir": str(tmp_path / "g"), "printers": []}))
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("PRINTSHARE_BRIDGE", "0")          # recorded, so the "1" set by the command is undone afterwards
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: calls.setdefault("run", (a, k)))
    assert cli.main(["bridge"]) == 0
    import os
    assert os.environ["PRINTSHARE_BRIDGE"] == "1" and calls["run"][0][0] == "printshare.api:app"
    assert load_settings(tmp_path / "config.yaml").bridge is True


def test_default_bridge_name(monkeypatch):
    monkeypatch.setenv("PRINTSHARE_NAME", "Tower")
    assert default_name() == "PocketPrint3D (Tower)"
    monkeypatch.setenv("PRINTSHARE_NAME", "6e6e186d9362")
    assert default_name() == "PocketPrint3D Server"
