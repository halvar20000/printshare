"""Own OrcaSlicer presets uploaded from the app (issue #2)."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from printshare import user_profiles
from printshare.bootstrap import ensure_config
from printshare.config import load_settings
from printshare.profiles import ProfileLibrary

AFC = Path(__file__).parent / "data" / "afc_cosmos_machine.json"   # Dominique's COSMOS AFC printer preset
CC = "Elegoo Centauri Carbon 0.4 nozzle"
NO_HA = Path("/nonexistent/options.json")


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "orca" / "Elegoo"
    for kind, presets in {
        "machine": [{"name": CC, "printable_area": ["0x0", "256x0", "256x256", "0x256"],
                     "machine_start_gcode": "M729 ; Elegoo clean nozzle"}],
        "process": [{"name": "0.20mm Standard @Elegoo CC 0.4 nozzle", "compatible_printers": [CC]}],
        "filament": [{"name": "Elegoo PLA @ECC", "compatible_printers": [CC]}],
    }.items():
        (root / kind).mkdir(parents=True)
        for p in presets:
            (root / kind / f"{p['name']}.json").write_text(json.dumps(p))
    return ProfileLibrary(tmp_path / "orca")


@pytest.fixture
def cfg(tmp_path, lib):
    """Managed config like the Unraid template writes it: a COSMOS printer."""
    c = tmp_path / "config" / "config.yaml"
    c.parent.mkdir()
    c.write_text(f"work_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\norca_profiles_dir: {lib.profiles_dir}\n")
    env = {"PRINTER_NAME": "Dominique", "PRINTER_TYPE": "moonraker", "PRINTER_ADDRESS": "192.168.0.95"}
    ensure_config(c, env, NO_HA)
    return c, env


def test_upload_single_preset(tmp_path, lib):
    out = user_profiles.store(tmp_path, "AFC COSMOS.json", AFC.read_bytes(), lib)
    assert len(out) == 1
    info = out[0]
    assert (info["kind"], info["inherits"], info["print_start"]) == ("machine", CC, True)
    stored = json.loads((tmp_path / "profiles" / info["file"]).read_text())
    assert stored["name"].startswith("AFC COSMOS") and "print_host" not in stored
    assert [p["file"] for p in user_profiles.list_profiles(tmp_path, lib)] == [info["file"]]


def test_upload_bundle(tmp_path, lib):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bundle_structure.json", json.dumps({"printer_config": ["printer/AFC.json"]}))
        z.writestr("printer/AFC.json", AFC.read_text())
        z.writestr("filament/My PLA.json", json.dumps({"name": "My PLA", "inherits": "Elegoo PLA @ECC",
                                                       "filament_type": ["PLA"], "from": "User"}))
    out = user_profiles.store(tmp_path, "Cosmos.orca_printer", buf.getvalue(), lib)
    assert sorted(p["kind"] for p in out) == ["filament", "machine"]


@pytest.mark.parametrize("content,match", [
    (b"", "empty"),
    (b"{not json", "not a valid JSON"),
    (b"[1, 2]", "not an OrcaSlicer preset"),
    (json.dumps({"name": "x", "foo": 1}).encode(), "printer, process or filament"),
    (json.dumps({"name": "x", "inherits": "Prusa MK99", "printer_model": "x"}).encode(), "does not know"),
    (b"PK\x03\x04broken", "not a valid preset bundle"),
])
def test_upload_is_checked(tmp_path, lib, content, match):
    with pytest.raises(user_profiles.ProfileUploadError, match=match):
        user_profiles.store(tmp_path, "p.json", content, lib)
    assert not (tmp_path / "profiles").exists() or not list((tmp_path / "profiles").iterdir())


def test_assignment_survives_regenerated_config(cfg, lib):
    c, env = cfg
    conf_dir = c.parent
    file = user_profiles.store(conf_dir, "afc.json", AFC.read_bytes(), lib)[0]["file"]
    assert load_settings(c).printers[0].slicing.machine_preset == "cosmos"      # before: built-in preset

    user_profiles.assign_machine(conf_dir, "dominique", file, lib)
    s = load_settings(c).printers[0].slicing
    assert s.machine_file == str(conf_dir / "profiles" / file) and s.machine == CC
    assert s.machine_preset is None           # the uploaded preset has its own PRINT_START (not overridden)

    ensure_config(c, env, NO_HA)              # Unraid/HA regenerate config.yaml on every start
    assert "machine_file" not in c.read_text()
    assert load_settings(c).printers[0].slicing.machine_file.endswith(file)

    with pytest.raises(user_profiles.ProfileUploadError, match="in use"):
        user_profiles.delete(conf_dir, file, ["dominique"])
    user_profiles.assign_machine(conf_dir, "dominique", None, lib)
    assert not (conf_dir / "printers.d" / "dominique.yaml").exists()
    assert load_settings(c).printers[0].slicing.machine_preset == "cosmos"
    user_profiles.delete(conf_dir, file, ["dominique"])
    assert not (conf_dir / "profiles" / file).exists()


def test_only_plain_names(tmp_path, lib):
    for bad in ("../config.yaml", "../../etc/passwd.json", ".hidden.json", "a/b.json"):
        with pytest.raises(user_profiles.ProfileUploadError):
            user_profiles.resolve_file(tmp_path, bad)
    filament = user_profiles.store(tmp_path, "f.json", json.dumps(
        {"name": "My PLA", "inherits": "Elegoo PLA @ECC", "filament_type": ["PLA"]}).encode(), lib)[0]["file"]
    with pytest.raises(user_profiles.ProfileUploadError, match="not a printer preset"):
        user_profiles.assign_machine(tmp_path, "x", filament, lib)


def test_profile_api(tmp_path, lib, monkeypatch):
    import importlib
    import os

    from fastapi.testclient import TestClient
    c = tmp_path / "cfg" / "config.yaml"
    c.parent.mkdir()
    c.write_text(f"api_token: t\nwork_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\n"
                 f"orca_profiles_dir: {lib.profiles_dir}\nprinters:\n  - id: dom\n    type: moonraker\n"
                 "    url: http://127.0.0.1:7125\n    slicing:\n      machine_preset: cosmos\n")
    monkeypatch.setenv("PRINTSHARE_CONFIG", str(c))
    api = importlib.reload(importlib.import_module("printshare.api"))
    h = {"Authorization": "Bearer t"}
    with TestClient(api.app) as client:
        assert client.post("/api/profiles", content=AFC.read_bytes()).status_code == 401
        r = client.post("/api/profiles", headers=h, params={"filename": "afc.json"}, content=AFC.read_bytes())
        assert r.status_code == 200, r.text
        file = r.json()[0]["file"]
        bad = client.post("/api/profiles", headers=h, params={"filename": "x.json"}, content=b"{nope")
        assert bad.status_code == 400 and "JSON" in bad.json()["detail"]
        assert client.get("/api/profiles", headers=h).json()[0]["file"] == file
        assert client.get("/api/printers/dom/profile", headers=h).json()["machine_preset"] == "cosmos"
        p = client.put("/api/printers/dom/profile", headers=h, json={"machine_file": file}).json()
        assert p["machine_file"] == file and p["machine_preset"] is None and p["machine"] == CC
        assert api.settings.printers[0].slicing.machine_file.endswith(file)   # live, no restart
        assert client.delete(f"/api/profiles/{file}", headers=h).status_code == 400   # in use
        assert client.put("/api/printers/dom/profile", headers=h, json={"machine_file": None}).json()["machine_file"] is None
        assert client.delete(f"/api/profiles/{file}", headers=h).status_code == 200
        assert client.put("/api/printers/dom/profile", headers=h, json={"machine_file": "../x.json"}).status_code == 400
    os.environ.pop("PRINTSHARE_CONFIG", None)
