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
    Path(s.work_dir).mkdir()
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
