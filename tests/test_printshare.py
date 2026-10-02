"""Tests. Slicing tests need OrcaSlicer: set ORCA_ROOT to the extracted AppImage dir."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from printshare.config import PrinterConfig, Settings, SlicingConfig
from printshare.fetch import FetchError, RemoteFile, choose_file, parse_source
from printshare.pipeline import run_job
from printshare.printers import get_adapter

from .fakes import FakeCentauri, FakeMoonraker

ORCA_ROOT = os.environ.get("ORCA_ROOT", "/opt/orca")
HAS_ORCA = Path(ORCA_ROOT, "AppRun").exists()
needs_orca = pytest.mark.skipif(not HAS_ORCA, reason="OrcaSlicer not available")


# ---------- fetch ----------
def test_parse_source():
    assert parse_source("https://www.printables.com/model/123456-benchy") == ("printables", "123456")
    assert parse_source("https://www.printables.com/de/model/99-x/files") == ("printables", "99")
    assert parse_source("https://www.thingiverse.com/thing:763622") == ("thingiverse", "763622")
    assert parse_source("https://example.com/a/part.stl")[0] == "url"
    with pytest.raises(FetchError):
        parse_source("not a link")


def test_choose_file():
    fs = [RemoteFile("printables", "1", str(i), n) for i, n in
          enumerate(["readme.pdf", "body.stl", "lid.stl"])]
    with pytest.raises(FetchError, match="choose one"):
        choose_file(fs, None)
    assert choose_file(fs, 2).name == "lid.stl"
    assert choose_file(fs, "body").name == "body.stl"
    assert choose_file(fs + [RemoteFile("printables", "1", "9", "plate.3mf")], None).name == "plate.3mf"


# ---------- printer adapters against fakes ----------
def test_moonraker_adapter(tmp_path):
    async def go():
        fake = FakeMoonraker(port=7125)
        await fake.start()
        try:
            g = tmp_path / "cube.gcode"
            g.write_text("PRINT_START\nG1 X1\nPRINT_END\n")
            # URL without port: first candidate (port 80) fails, :7125 fallback must work
            ad = get_adapter(PrinterConfig(id="m", type="moonraker", url="http://127.0.0.1"))
            res = await ad.send(g, start=True)
            st = await ad.status()
        finally:
            await fake.stop()
        return fake, res, st
    fake, res, st = asyncio.run(go())
    assert res == {"uploaded": "cube.gcode", "started": True}
    assert fake.uploads[0]["root"] == "gcodes" and fake.uploads[0]["print"] == "true"
    assert st["state"] == "printing" and st["progress"] == 3.1 and st["layer"] == 3


def test_elegoo_adapter(tmp_path):
    async def go():
        fake = FakeCentauri()
        await fake.start()
        try:
            g = tmp_path / "big.gcode"
            g.write_bytes(os.urandom(2_500_000))  # forces 3 chunks
            ad = get_adapter(PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1"))
            res = await ad.send(g, start=True)
            st = await ad.status()
        finally:
            await fake.stop()
        return fake, res, st, g
    fake, res, st, g = asyncio.run(go())
    assert res == {"uploaded": "big.gcode", "started": True}
    assert fake.files["big.gcode"] == g.read_bytes()
    start = [c for c in fake.commands if c["Cmd"] == 128][0]
    assert start["Data"]["Filename"] == "big.gcode"
    assert "nozzle" in st
    assert st["state"] == "printing" and st["file"] == "big.gcode"


def _send_with_dropped_starts(tmp_path, dropped, rest_status=0):
    async def go():
        fake = FakeCentauri(drop_starts=dropped, rest_status=rest_status)
        await fake.start()
        try:
            g = tmp_path / "part.gcode"
            g.write_text("G1 X1\n")
            ad = get_adapter(PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1",
                                           mainboard_id="FAKECC0001"))
            try:
                return fake, await ad.send(g, start=True)
            except Exception as e:  # noqa: BLE001
                return fake, e
        finally:
            await fake.stop()
    return asyncio.run(go())


def test_elegoo_start_retried_when_silently_dropped(tmp_path, monkeypatch):
    # live CC1: a start right after the upload is acknowledged but ignored
    monkeypatch.setattr("printshare.printers.elegoo.START_TIMEOUT_S", 3)
    fake, res = _send_with_dropped_starts(tmp_path, dropped=1)
    assert res == {"uploaded": "part.gcode", "started": True}
    assert [c["Cmd"] for c in fake.commands].count(128) == 2
    assert fake.printing == "part.gcode"


@pytest.mark.parametrize("rest_status", [8, 9])
def test_elegoo_dropped_start_detected_after_previous_print(tmp_path, monkeypatch, rest_status):
    # live 2026-09-28: printer still "completed" from the last print -> that is not a new start
    monkeypatch.setattr("printshare.printers.elegoo.START_TIMEOUT_S", 3)
    fake, res = _send_with_dropped_starts(tmp_path, dropped=1, rest_status=rest_status)
    assert res == {"uploaded": "part.gcode", "started": True}
    assert [c["Cmd"] for c in fake.commands].count(128) == 2 and fake.printing == "part.gcode"


def test_elegoo_start_that_never_happens_is_an_error(tmp_path, monkeypatch):
    from printshare.printers.elegoo import PrinterStartError
    monkeypatch.setattr("printshare.printers.elegoo.START_TIMEOUT_S", 3)
    fake, res = _send_with_dropped_starts(tmp_path, dropped=5)
    assert isinstance(res, PrinterStartError) and "did not start part.gcode" in str(res)
    assert fake.files["part.gcode"] and fake.printing is None


# ---------- slicing + full pipeline ----------
def _settings(tmp_path) -> Settings:
    s = Settings(orca_binary=f"{ORCA_ROOT}/AppRun", orca_profiles_dir=f"{ORCA_ROOT}/resources/profiles",
                 work_dir=str(tmp_path / "work"), gcode_dir=str(tmp_path / "gcode"))
    Path(s.work_dir).mkdir(parents=True)
    return s


def _cube(tmp_path) -> Path:
    import trimesh
    p = tmp_path / "cube.stl"
    trimesh.creation.box(extents=(20, 20, 20)).export(p)
    return p


@needs_orca
def test_pipeline_cosmos_moonraker(tmp_path):
    s = _settings(tmp_path)
    s.printers = [PrinterConfig(id="dom", type="moonraker", url="http://127.0.0.1:7125",
                                slicing=SlicingConfig(machine_preset="cosmos"))]
    model = _cube(tmp_path)

    async def go():
        fake = FakeMoonraker()
        await fake.start()
        try:
            return fake, await run_job(s, str(model), "dom")
        finally:
            await fake.stop()
    fake, res = asyncio.run(go())
    gcode = fake.uploads[0]["data"].decode()
    assert "PRINT_START EXTRUDER=" in gcode and "BED=60" in gcode
    assert "TOOL=0" in gcode and "SET_PRINT_STATS_INFO TOTAL_LAYER=" in gcode   # AFC start (Dominique's profile)
    assert "M729" not in gcode and "M8213" not in gcode      # would e-stop COSMOS
    assert res.print_time and res.filament_g


@needs_orca
def test_pipeline_stock_elegoo(tmp_path):
    s = _settings(tmp_path)
    s.printers = [PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1")]
    model = _cube(tmp_path)

    async def go():
        fake = FakeCentauri()
        await fake.start()
        try:
            return fake, await run_job(s, str(model), "cc")
        finally:
            await fake.stop()
    fake, res = asyncio.run(go())
    gcode = fake.files["cube.gcode"].decode()
    assert ";printer_model:Elegoo Centauri Carbon" in gcode
    assert "M190 S60" in gcode
    assert any(c["Cmd"] == 128 for c in fake.commands)


@pytest.mark.parametrize("leveling,expected", [(None, 1), (True, 1), (False, 0)])
def test_elegoo_leveling_per_print(tmp_path, leveling, expected):
    async def go():
        fake = FakeCentauri()
        await fake.start()
        try:
            g = tmp_path / "part.gcode"
            g.write_text("G1 X1\n")
            ad = get_adapter(PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1",
                                           mainboard_id="FAKECC0001"))
            await ad.send(g, start=True, leveling=leveling)
            return fake
        finally:
            await fake.stop()
    fake = asyncio.run(go())
    start = [c for c in fake.commands if c["Cmd"] == 128][0]
    assert start["Data"]["Calibration_switch"] == expected


def _two_colour_3mf(tmp_path) -> Path:
    """A real OrcaSlicer project with two objects: filament 1 red, filament 2 green - like a multicolour
    model from Printables/MakerWorld. Made by OrcaSlicer itself: it crashes on hand-written project 3MFs
    that lack parts of its project structure (plates, object files …)."""
    import subprocess

    import trimesh

    from printshare.slicer import Slicer
    s = _settings(tmp_path / "project")
    printer = PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1")
    work = tmp_path / "project"
    m, p, fs = Slicer(s).build_presets(printer, work, printer.slicing.__class__(
        filaments=["Elegoo PLA @ECC", "Elegoo PLA @ECC"]), ["#FF0000", "#00AE42"])
    for name in ("red", "green"):
        trimesh.creation.box(extents=(20, 20, 10)).export(work / f"{name}.stl")
    r = subprocess.run([s.orca_binary, "--arrange", "1", "--load-settings", f"{m};{p}",
                        "--load-filaments", ";".join(map(str, fs)), "--load-filament-ids", "1,2",
                        "--slice", "1", "--outputdir", str(work / "out"), "--export-3mf", "two_colours.3mf",
                        str(work / "red.stl"), str(work / "green.stl")],
                       capture_output=True, text=True, cwd=work, timeout=300)
    path = work / "out" / "two_colours.3mf"
    assert path.is_file(), r.stdout[-2000:] + r.stderr[-2000:]
    return path


@needs_orca
def test_slice_two_colour_3mf_for_centauri(tmp_path):
    """Real OrcaSlicer: one filament preset per model colour; CANVAS colour changes in the G-code."""
    from printshare.config import JobOptions
    from printshare.gcode_preview import build
    from printshare.slicer import Slicer
    s = _settings(tmp_path)
    printer = PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1")
    slicing = JobOptions(filaments=["Elegoo PLA @ECC", "Elegoo PLA @ECC"]).apply(printer.slicing)
    res = Slicer(s).slice(_two_colour_3mf(tmp_path), printer, tmp_path / "out", slicing)
    gcode = res.gcode_path.read_text()
    assert "\nT1" in gcode, res.log[-3000:]                       # switches to filament 2
    assert "M6211" in gcode                                       # CANVAS change on stock firmware
    assert [f["color"] for f in res.filaments] == ["#FF0000", "#00AE42"]
    assert all(f["grams"] and f["grams"] > 0 for f in res.filaments), res.filaments
    preview = build(res.gcode_path)
    assert preview["filament_colors"][:2] == ["#FF0000", "#00AE42"]
    assert {p[1] for lay in preview["layers"] for p in lay["paths"]} >= {0, 1}


def test_cosmos_preset_uses_afc_tool_changes():
    """Dominique's COSMOS AFC profile: AFC tool change instead of Elegoo's CANVAS M6211."""
    o = SlicingConfig(machine_preset="cosmos").machine_overrides
    assert o["change_filament_gcode"].startswith("T[next_extruder] PURGE_LENGTH=[flush_length]")
    assert "M6211" not in o["change_filament_gcode"] and "TOOL={initial_tool}" in o["machine_start_gcode"]
    assert o["cooling_tube_length"] == "0" and o["parking_pos_retraction"] == "0"


@needs_orca
def test_slice_two_colour_3mf_for_cosmos_afc(tmp_path):
    from printshare.config import JobOptions
    from printshare.slicer import Slicer
    s = _settings(tmp_path)
    printer = PrinterConfig(id="dom", type="moonraker", url="http://127.0.0.1:7125",
                            slicing=SlicingConfig(machine_preset="cosmos"))
    slicing = JobOptions(filaments=["Elegoo PLA @ECC", "Elegoo PLA @ECC"]).apply(printer.slicing)
    res = Slicer(s).slice(_two_colour_3mf(tmp_path), printer, tmp_path / "out", slicing)
    gcode = res.gcode_path.read_text()
    assert "T1 PURGE_LENGTH=" in gcode, res.log[-3000:]    # AFC switches to filament 2
    assert "M6211" not in gcode                           # Elegoo's CANVAS command is not for COSMOS
    assert "TOOL=0" in gcode and "M729" not in gcode
    assert len(res.filaments) == 2 and all(f["grams"] for f in res.filaments)
    # lane selection (issue #6) on the real G-code: colour 1 -> lane T2, colour 2 -> lane T3
    from printshare.lanes import remap_tools
    mapped = remap_tools(res.gcode_path, {0: 2, 1: 3}, tmp_path / "mapped").read_text()
    code = [ln for ln in mapped.splitlines() if not ln.startswith(";")]
    assert any("PRINT_START" in ln and "TOOL=2" in ln for ln in code)
    assert any(ln.startswith("T3 PURGE_LENGTH=") for ln in code)
    assert not any(ln.startswith(("T0", "T1")) for ln in code)


@needs_orca
def test_uploaded_afc_cosmos_preset_slices(tmp_path):
    """Issue #2: Dominique's own COSMOS AFC printer preset, uploaded and assigned like from the app."""
    from printshare import user_profiles
    from printshare.config import load_settings
    from printshare.profiles import ProfileLibrary
    from printshare.slicer import Slicer
    conf = tmp_path / "cfg"
    conf.mkdir()
    (conf / "config.yaml").write_text(
        f"work_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\norca_binary: {ORCA_ROOT}/AppRun\n"
        f"orca_profiles_dir: {ORCA_ROOT}/resources/profiles\nprinters:\n  - id: dom\n    type: moonraker\n"
        "    url: http://127.0.0.1:7125\n    slicing:\n      machine_preset: cosmos\n")
    lib = ProfileLibrary.cached(f"{ORCA_ROOT}/resources/profiles")
    afc = Path(__file__).parent / "data" / "afc_cosmos_machine.json"
    file = user_profiles.store(conf, afc.name, afc.read_bytes(), lib)[0]["file"]
    user_profiles.assign_machine(conf, "dom", file, lib)
    s = load_settings(conf / "config.yaml")
    printer = s.printers[0]
    assert printer.slicing.machine_preset is None
    res = Slicer(s).slice(_cube(tmp_path), printer, tmp_path / "out")
    gcode = res.gcode_path.read_text()
    assert "PRINT_START EXTRUDER=2" in gcode and "BED=60" in gcode and "TOOL=0" in gcode, gcode[:3000]
    code = "\n".join(line for line in gcode.splitlines() if not line.startswith(";"))  # without the settings dump
    assert "[first_layer_temperature]" not in code and "SET_PRINT_STATS_INFO TOTAL_LAYER=" in code
    assert "M729" not in gcode and "M6211" not in gcode


@needs_orca
def test_slice_with_own_process_and_filament_presets(tmp_path):
    """Uploaded quality + material presets (#2, groundwork for Orca Cloud #7) are used by the real Orca."""
    import json

    from printshare import user_profiles
    from printshare.config import JobOptions, load_settings
    from printshare.profiles import ProfileLibrary
    from printshare.slicer import Slicer
    conf = tmp_path / "cfg"
    conf.mkdir()
    (conf / "config.yaml").write_text(
        f"work_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\norca_binary: {ORCA_ROOT}/AppRun\n"
        f"orca_profiles_dir: {ORCA_ROOT}/resources/profiles\nprinters:\n  - id: cc\n    type: elegoo_sdcp\n"
        "    host: 127.0.0.1\n")
    lib = ProfileLibrary.cached(f"{ORCA_ROOT}/resources/profiles")
    own = [{"name": "Meine PLA", "inherits": "Elegoo PLA @ECC", "from": "User", "filament_settings_id": ["Meine PLA"],
            "nozzle_temperature": ["205"], "nozzle_temperature_initial_layer": ["205"]},
           {"name": "Mein Standard", "inherits": "0.20mm Standard @Elegoo CC 0.4 nozzle", "from": "User",
            "print_settings_id": "Mein Standard", "wall_loops": "4"}]
    for p in own:
        user_profiles.store(conf, f"{p['name']}.json", json.dumps(p).encode(), lib)
    s = load_settings(conf / "config.yaml")
    Path(s.work_dir).mkdir(parents=True, exist_ok=True)
    printer = s.printers[0]
    slicing = JobOptions(filament="Meine PLA", process="Mein Standard").apply(printer.slicing)
    res = Slicer(s).slice(_cube(tmp_path), printer, tmp_path / "out", slicing)
    gcode = res.gcode_path.read_text()
    assert "M104 S205" in gcode or "M109 S205" in gcode, "own filament temperature not used"
    assert "; wall_loops = 4" in gcode and "; filament_settings_id = \"Meine PLA\"" in gcode


def test_compatible_printers_condition():
    """Prusa / CORE One presets pick their printers by condition, as OrcaSlicer evaluates it."""
    from printshare.profiles import condition_matches
    mk4s = {"printer_notes": "Don't remove\nPRINTER_VENDOR_PRUSA3D\nPRINTER_MODEL_MK4S\n", "nozzle_diameter": ["0.4"]}
    hf = {**mk4s, "printer_notes": mk4s["printer_notes"] + "HF_NOZZLE\n"}
    plain = "printer_notes=~/.*MK4S.*/ and nozzle_diameter[0]==0.4"
    assert condition_matches(plain, mk4s) and condition_matches(plain, hf)
    assert not condition_matches(plain, {**mk4s, "nozzle_diameter": ["0.6"]})
    no_hf = plain + " and printer_notes!~/.*HF_NOZZLE.*/"
    assert condition_matches(no_hf, mk4s) and not condition_matches(no_hf, hf)
    core = "printer_notes=~/.*PRINTER_MODEL_COREONE[^_a-zA-Z0-9].*/ and nozzle_diameter[0]==0.4"
    assert condition_matches(core, {"printer_notes": "PRINTER_MODEL_COREONE\n", "nozzle_diameter": ["0.4"]})
    assert not condition_matches(core, {"printer_notes": "PRINTER_MODEL_COREONE_L\n", "nozzle_diameter": ["0.4"]})
    assert condition_matches("printer_notes=~/.*MK4S.*/ and single_extruder_multi_material",
                             {**mk4s, "single_extruder_multi_material": "1"})
    assert not condition_matches("printer_notes=~/.*MK4S.*/ and single_extruder_multi_material",
                                 {**mk4s, "single_extruder_multi_material": "0"})
    assert condition_matches("nozzle_diameter[0]==0.6 or printer_notes=~/.*MK4S.*/", mk4s)
    assert not condition_matches("num_extruders() > 1 &&", mk4s)       # unknown syntax: never offered


@needs_orca
def test_prusa_qualities_and_library_materials_slice(tmp_path):
    """A cloud Prusa printer (PrusaLink via the app): Prusa's own qualities (selected by condition) and the
    printer-independent material library are offered and slice with the real Orca."""
    from printshare.config import JobOptions
    from printshare.profiles import ProfileLibrary
    from printshare.slicer import Slicer
    lib = ProfileLibrary.cached(f"{ORCA_ROOT}/resources/profiles")
    mk4s = "Prusa MK4S 0.4 nozzle"
    qualities, materials = lib.compatible("process", mk4s), lib.compatible("filament", mk4s)
    assert "0.20mm SPEED @MK4S 0.4" in qualities and "0.15mm STRUCTURAL @MK4S 0.4" in qualities
    assert not [q for q in qualities if "HF" in q or "Elegoo" in q]
    assert "Prusa Generic PLA @MK4S" in materials and "Generic PETG @System" in materials
    assert "Generic PETG @System" in lib.compatible("filament", "Elegoo Centauri Carbon 0.4 nozzle")
    s = _settings(tmp_path)
    s.printers = [PrinterConfig(id="mk4s", type="prusalink", url="http://127.0.0.1",
                                slicing=SlicingConfig(machine=mk4s, process="0.20mm SPEED @MK4S 0.4",
                                                      filament="Prusa Generic PLA @MK4S")),
                  PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1")]
    for pid, process, filament, model in (("mk4s", "0.15mm STRUCTURAL @MK4S 0.4", "Generic PETG @System", "MK4S"),
                                          ("cc", None, "Generic PETG @System", "Elegoo Centauri Carbon")):
        printer = s.printer(pid)
        slicing = JobOptions(process=process, filament=filament).apply(printer.slicing)
        res = Slicer(s).slice(_cube(tmp_path), printer, tmp_path / f"out-{pid}", slicing)
        gcode = res.gcode_path.read_text()
        assert model in gcode
        assert '; filament_settings_id = "Generic PETG @System"' in gcode and res.print_time
        if pid == "mk4s":
            assert "; print_settings_id = 0.15mm STRUCTURAL @MK4S 0.4" in gcode


@needs_orca
def test_orca_cloud_bundle_preset_slices(tmp_path):
    """A printer preset from a shared Orca Cloud bundle (#7, recorded COSMOS bundle) slices with the real Orca."""
    import json

    import httpx

    from printshare import orca_cloud
    from printshare.config import load_settings
    from printshare.profiles import ProfileLibrary
    from printshare.slicer import Slicer
    conf = tmp_path / "cfg"
    conf.mkdir()
    (conf / "config.yaml").write_text(
        f"work_dir: {tmp_path / 'w'}\ngcode_dir: {tmp_path / 'g'}\norca_binary: {ORCA_ROOT}/AppRun\n"
        f"orca_profiles_dir: {ORCA_ROOT}/resources/profiles\nprinters:\n  - id: dom\n    type: moonraker\n"
        "    url: http://127.0.0.1:7125\n")
    lib = ProfileLibrary.cached(f"{ORCA_ROOT}/resources/profiles")
    bundle = json.loads((Path(__file__).parent / "data" / "orca_cloud_cosmos_bundle.json").read_text())
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=bundle)))
    out = orca_cloud.import_bundle(conf, "https://cloud.orcaslicer.com/b/3fad3c38f25f", lib, http)
    assert len(out["imported"]) == 8 and not out["skipped"]
    afc = next(p for p in out["imported"] if p["name"] == "Elegoo Centauri Carbon 0.4 nozzle - Cosmos AFC")
    from printshare import user_profiles
    user_profiles.assign_machine(conf, "dom", afc["file"], lib)
    s = load_settings(conf / "config.yaml")
    Path(s.work_dir).mkdir(parents=True, exist_ok=True)
    printer = s.printers[0]
    res = Slicer(s).slice(_cube(tmp_path), printer, tmp_path / "out", printer.slicing)
    code = "\n".join(line for line in res.gcode_path.read_text().splitlines() if not line.startswith(";"))
    assert "PRINT_START" in code and "SET_PRINT_STATS_INFO TOTAL_LAYER=" in code and "M729" not in code
