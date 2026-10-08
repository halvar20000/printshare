"""Moving the printer by hand (printshare/motion.py, 0.43.0): home, jog, extrude, filament, macros."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from printshare import motion
from printshare.config import PrinterConfig
from printshare.printers import get_adapter

from .fakes import FakeCentauri, FakeMoonraker
from .test_api import H, BackgroundFake, api, client  # noqa: F401 (fixtures)
from .test_bambu import fake  # noqa: F401 (fixture)
from .test_controls import MOON, run

COSMOS = json.loads((Path(__file__).parent / "data" / "cosmos_afc_moonraker.json").read_text())


def test_check_and_gcode():
    caps = {"home": ["XYZ", "X"], "jog": {"axes": ["X", "Z"], "steps": [0.1, 1, 10]}, "extrude": True,
            "unload": True, "macros": ["CLEAN_NOZZLE"]}
    motion.check(caps, "home", "XYZ")
    motion.check(caps, "jog", "Z", -10)
    motion.check(caps, "extrude", None, -5)
    motion.check(caps, "macro", macro="CLEAN_NOZZLE")
    for args, msg in ((("home", "Y"), "axis must be"), (("jog", "Y", 1), "can't move"), (("jog", "X", 11), "between"),
                      (("jog", "X", 0), "between"), (("extrude", None, 500), "between"), (("load",), "can't load"),
                      (("fly",), "action must be")):
        with pytest.raises(motion.MotionError, match=msg):
            motion.check(caps, *args)
    with pytest.raises(motion.MotionError, match="unknown macro"):
        motion.check(caps, "macro", macro="SAVE_CONFIG")
    assert motion.jog_gcode("Z", -0.1) == "G91\nG1 Z-0.1 F600\nG90" and motion.home_gcode("X") == "G28 X"
    assert motion.klipper_macros(["gcode_macro CLEAN_NOZZLE", "gcode_macro _HIDDEN", "gcode_macro M600",
                                  "gcode_macro PRINT_START", "gcode_macro bed_mesh_calibrate", "extruder"]) == \
        ["BED_MESH_CALIBRATE", "CLEAN_NOZZLE"]


def test_moonraker_motion_with_cosmos_macros():
    fk = FakeMoonraker(recorded=COSMOS)
    ad = get_adapter(MOON)

    async def go():
        caps = await ad.motion()
        for a in (("home", "XYZ"), ("jog", "X", 10), ("extrude", None, -2), ("motors_off",),
                  ("macro", None, None, "CLEAN_NOZZLE")):
            await ad.move(*a)
        await ad.move("unload", temp=250)          # COSMOS has UNLOAD_FILAMENT: heated first
        await ad.move("load", temp=220)            # … but no LOAD_FILAMENT: plain G-code
        fk.gcode_error = "Must home axis first: 10.000 0.000 0.000 [0.000]"
        try:
            await ad.move("jog", "X", 10)
        except Exception as e:  # noqa: BLE001
            return caps, str(e)
    caps, err = run(fk, go)
    assert caps["unload"] is True and caps["load"] is True and caps["filament_temp"] is True
    assert "CLEAN_NOZZLE" in caps["macros"] and "BED_MESH_CALIBRATE" in caps["macros"]
    assert not {"PRINT_START", "SAVE_CONFIG", "UNLOAD_FILAMENT", "M600", "_CG28"} & set(caps["macros"])
    assert fk.scripts[:5] == ["G28", "G91\nG1 X10 F3000\nG90", "M83\nG1 E-2 F300", "M84", "CLEAN_NOZZLE"]
    assert fk.scripts[5] == "M109 S250\nUNLOAD_FILAMENT"
    assert fk.scripts[6].startswith("; PocketPrint3D filament load at 220 C\nM104 S220\nM109 S220\nM83\nG92 E0\n"
                                     "G1 E25 F240\nG1 E25 F240\nG1 E25 F240\nG1 E15 F240\n")
    assert fk.scripts[6].endswith("M104 S0\n")
    assert "Must home axis first" in err


def test_centauri_home_and_jog():
    fk = FakeCentauri()
    ad = get_adapter(PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1", mainboard_id="FAKECC0001"))

    async def go():
        await ad.move("home", "XYZ")
        await ad.move("jog", "Z", -0.1)
        with pytest.raises(ValueError, match="can't extrude"):
            await ad.move("extrude", None, 5)
        for action in ("load", "unload"):             # the stock firmware can't (tried on the real CC)
            with pytest.raises(ValueError, match="can't"):
                await ad.move(action, temp=220)
    run(fk, go)
    sent = [(c["Cmd"], c["Data"]) for c in fk.commands if c["Cmd"] in (401, 402)]
    assert sent == [(402, {"Axis": "XYZ"}), (401, {"Axis": "Z", "Step": -0.1})]
    assert ad.motion()["extrude"] is False and ad.motion()["jog"]["steps"] == [0.1, 1, 10, 100]
    assert ad.motion()["load"] is False and ad.motion()["unload"] is False and not fk.files


def test_filament_files_are_not_jobs():
    from printshare import jobtrack
    assert jobtrack.external([], "cc", {"file": "/local/pp3d-filament-load.gcode", "progress": 3}, "active") is None
    assert jobtrack.external([], "cc", {"file": "/local/cube.gcode", "progress": 3}, "active") is not None


def test_bambu_motion(fake):  # noqa: F811
    import asyncio
    link, _ = fake
    link.report["home_flag"] = 7                  # X, Y, Z homed
    ad = get_adapter(PrinterConfig(id="p1s", type="bambu_lan", host="192.168.1.53", password="12345678"))

    async def go():
        await ad.move("home", "XYZ")
        await ad.move("jog", "Y", -10)
        await ad.move("extrude", None, 5)
        await ad.move("unload", temp=250)
        await ad.move("load", temp=220, slot=1)
        return await ad.motion()
    caps = asyncio.run(go())
    lines = [p["print"]["param"] for p in link.sent if (p.get("print") or {}).get("command") == "gcode_line"]
    assert lines[0] == "G28 \n" and "G1 Y-10.0 F3000" in lines[1] and lines[1].startswith("M211 S")
    assert lines[2] == "M83 \nG0 E5.0 F300\n"
    changes = [p["print"] for p in link.sent if (p.get("print") or {}).get("command") == "ams_change_filament"]
    assert [(c["target"], c["tar_temp"]) for c in changes] == [(255, 250), (1, 220)]
    assert caps["load"] and {s["tool"] for s in caps["load_slots"]} >= {0, 1}
    link.report["home_flag"] = 6505880          # as the real P1S after a print: axes not homed
    with pytest.raises(ValueError, match="not homed"):
        asyncio.run(ad.move("jog", "X", 10))


def test_api_motion(client):  # noqa: F811
    with BackgroundFake(FakeMoonraker(recorded=COSMOS)) as fk:
        caps = client.get("/api/printers/dom/motion", headers=H).json()
        assert caps["supported"] and caps["jog"]["axes"] == ["X", "Y", "Z"]
        assert client.post("/api/printers/dom/motion", headers=H, json={"action": "home", "axis": "xyz"}).status_code == 200
        assert client.post("/api/printers/dom/motion", headers=H,
                           json={"action": "jog", "axis": "Z", "distance": 500}).status_code == 400
        assert client.post("/api/printers/dom/motion", headers=H, json={"action": "unload"}).status_code == 409
        assert client.post("/api/printers/dom/motion", headers=H,
                           json={"action": "unload", "material": "PETG", "confirm": True}).status_code == 200
        assert client.post("/api/printers/dom/motion", headers=H,
                           json={"action": "unload", "material": "Wood", "confirm": True}).status_code == 400
        assert fk.scripts[-2:] == ["G28", "M109 S250\nUNLOAD_FILAMENT"]
        assert any(m["name"] == "PETG" for m in caps["materials"])


def test_filament_moves_stay_below_klippers_limit():
    # Klipper's max_extrude_only_distance (default 50 mm) drops longer extrude-only moves - and the rest of the file
    for action in ("load", "unload"):
        moves = [l for l in motion.filament_gcode(action, 220).splitlines() if l.startswith("G1 E")]
        lengths = [abs(float(l.split()[1][1:])) for l in moves]
        assert lengths and max(lengths) <= motion.MAX_E_MOVE
    unload = motion.filament_gcode("unload", 220)
    total = sum(float(l.split()[1][1:]) for l in unload.splitlines() if l.startswith("G1 E"))
    assert total == motion.UNLOAD_PUSH - motion.UNLOAD_TIP - motion.UNLOAD_MM
