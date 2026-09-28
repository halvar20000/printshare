"""First-start configuration from the Unraid template / Home Assistant add-on options."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from printshare.bootstrap import banner, ensure_config, remote_url, server_url
from printshare.cli import pairing_link
from printshare.config import load_settings

ROOT = Path(__file__).resolve().parent.parent
NO_HA = Path("/nonexistent/options.json")


def _seed(cfg: Path) -> None:
    """Keep work/G-code dirs in tmp (generated configs keep unrelated keys of an existing file)."""
    cfg.parent.mkdir(parents=True, exist_ok=True)
    with cfg.open("a") as fh:
        fh.write(f"work_dir: {cfg.parent / 'work'}\ngcode_dir: {cfg.parent / 'gcode'}\n")


def test_unraid_env_creates_managed_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    _seed(cfg)
    env = {"PRINTER_NAME": "Centauri Carbon", "PRINTER_TYPE": "elegoo_sdcp", "PRINTER_ADDRESS": "192.168.1.50"}
    info = ensure_config(cfg, env, NO_HA)
    assert info["managed"] and len(info["token"]) >= 20
    s = load_settings(cfg)
    p = s.printers[0]
    assert (p.id, p.type, p.host) == ("centauri-carbon", "elegoo_sdcp", "192.168.1.50")
    assert p.slicing.bed_type == "Textured PEI Plate" and p.slicing.machine_preset is None
    assert oct(cfg.stat().st_mode & 0o777) == "0o600"

    # restart with a changed form: printer updated, token kept, other settings kept
    cfg.write_text(cfg.read_text() + "max_parallel_slices: 2\n")
    env2 = {**env, "PRINTER_TYPE": "moonraker", "PRINTER_ADDRESS": "192.168.1.60"}
    info2 = ensure_config(cfg, env2, NO_HA)
    s2 = load_settings(cfg)
    assert info2["token"] == info["token"] and s2.api_token == info["token"]
    assert s2.max_parallel_slices == 2
    p2 = s2.printers[0]
    assert p2.url == "http://192.168.1.60" and p2.slicing.machine_preset == "cosmos"
    assert "PRINT_START" in p2.slicing.machine_overrides["machine_start_gcode"]


def test_home_assistant_options(tmp_path):
    opts = tmp_path / "options.json"
    opts.write_text(json.dumps({"api_token": "fixed-token", "thingiverse_token": "", "server_url": "192.168.1.5:8484",
                                "printers": [
                                    {"name": "Thomas", "type": "elegoo_sdcp", "address": "http://192.168.1.50/"},
                                    {"name": "Thomas", "type": "moonraker", "address": "192.168.1.60:7125",
                                     "cosmos": False, "build_plate": "High Temp Plate"}]}))
    cfg = tmp_path / "config.yaml"
    _seed(cfg)
    info = ensure_config(cfg, {}, opts)
    s = load_settings(cfg)
    assert info["token"] == "fixed-token" == s.api_token
    assert [p.id for p in s.printers] == ["thomas", "thomas-2"]
    assert s.printers[0].host == "192.168.1.50"
    assert s.printers[1].url == "http://192.168.1.60:7125" and s.printers[1].slicing.machine_preset is None
    assert s.printers[1].slicing.bed_type == "High Temp Plate"
    assert server_url({}, opts) == "http://192.168.1.5:8484"
    assert remote_url({"PRINTSHARE_REMOTE_URL": "100.64.0.1:8484"}, NO_HA) == "http://100.64.0.1:8484"
    assert remote_url({}, NO_HA) == ""
    text = banner(info, server_url({}, opts))
    assert "fixed-token" in text and "printshare://" not in text  # QR is drawn, not printed as text
    assert "Thomas" in text


def test_empty_env_token_keeps_auth(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("api_token: secret\nprinters: []\n")
    _seed(cfg)
    monkeypatch.setenv("PRINTSHARE_API_TOKEN", "")
    assert load_settings(cfg).api_token == "secret"
    monkeypatch.setenv("PRINTSHARE_API_TOKEN", "from-env")
    assert load_settings(cfg).api_token == "from-env"


def test_pairing_link_with_remote_address():
    assert pairing_link("http://192.168.1.5:8484/", "t k") == "printshare://connect?url=http%3A%2F%2F192.168.1.5%3A8484&token=t+k"
    assert pairing_link("http://a:1", "t", "http://100.64.0.1:8484/").endswith("&remote=http%3A%2F%2F100.64.0.1%3A8484")
    assert "away from home the app uses http://100.1:1" in banner({"token": "t", "printers": []}, "http://a:1", "http://100.1:1")


def test_file_mode_keeps_hand_written_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    original = "api_token: mine\nprinters:\n  - id: a\n    type: moonraker\n    url: http://x\n"
    cfg.write_text(original)
    info = ensure_config(cfg, {}, NO_HA)
    assert cfg.read_text() == original and not info["managed"] and info["token"] == "mine"


def test_first_start_without_printer_creates_empty_config(tmp_path):
    cfg = tmp_path / "sub" / "config.yaml"
    info = ensure_config(cfg, {}, NO_HA)
    _seed(cfg)
    s = load_settings(cfg)
    assert s.printers == [] and s.api_token == info["token"] and info["token"]
    assert "No printer configured" in banner(info, "")


@pytest.mark.parametrize("env", [
    {"PRINTER_ADDRESS": "1.2.3.4", "PRINTER_TYPE": "octoprint"},
    {"PRINTER_ADDRESS": "1.2.3.4", "BUILD_PLATE": "Glass"},
])
def test_invalid_form_values(tmp_path, env):
    with pytest.raises(ValueError):
        ensure_config(tmp_path / "config.yaml", env, NO_HA)


def test_packaging_versions_match():
    """HA only updates an add-on when its version changes; the image tag must exist for that version."""
    version = re.search(r'^version = "(.+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    addon = yaml.safe_load((ROOT / "homeassistant" / "printshare" / "config.yaml").read_text())
    assert addon["version"] == version
    assert addon["image"] == "ghcr.io/halvar20000/printshare"
    assert set(addon["arch"]) == {"amd64", "aarch64"}
    assert set(addon["options"]) <= set(addon["schema"])
    assert yaml.safe_load((ROOT / "repository.yaml").read_text())["name"]


def test_unraid_template():
    root = ET.parse(ROOT / "unraid" / "printshare.xml").getroot()
    assert root.findtext("Repository") == "ghcr.io/halvar20000/printshare:latest"
    targets = {c.get("Target") for c in root.findall("Config")}
    assert {"8484", "/config", "/data", "PRINTER_ADDRESS", "PRINTER_TYPE", "PRINTSHARE_URL", "PRINTSHARE_REMOTE_URL"} <= targets
    types = next(c for c in root.findall("Config") if c.get("Target") == "PRINTER_TYPE").get("Default")
    assert set(types.split("|")) == {"elegoo_sdcp", "moonraker"}


def test_no_stray_addon_configs():
    """The HA supervisor reads every config.{yaml,yml,json} in the repo as an add-on (recursive glob)."""
    hits = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("config.*")
            if p.suffix in (".yaml", ".yml", ".json")
            and not any(part.startswith(".") or part in ("node_modules", "rootfs") for part in p.parts)}
    assert hits <= {"homeassistant/printshare/config.yaml", "config.yaml"}, hits  # config.yaml: local, gitignored
