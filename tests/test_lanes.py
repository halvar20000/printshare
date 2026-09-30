"""Lane selection for AFC multi-filament units (issue #6)."""
from __future__ import annotations

import asyncio

import pytest

from printshare.config import PrinterConfig
from printshare.lanes import parse_mapping, remap_line, remap_tools
from printshare.printers import get_adapter

from .fakes import FakeMoonraker
from .test_api import H, BackgroundFake, _fake_prepare, _wait, api, client  # noqa: F401 (fixtures)

MAP = {0: 2, 1: 0}      # model filament 1 -> lane T2, filament 2 -> lane T0


@pytest.mark.parametrize("line,expected", [
    ("T1 PURGE_LENGTH=20.8292", "T0 PURGE_LENGTH=20.8292"),                 # AFC tool change (COSMOS)
    ("T0", "T2"),
    ("T1\n", "T0\n"),
    ("PRINT_START EXTRUDER=210 BED=60 CHAMBER=0 TOOL=0", "PRINT_START EXTRUDER=210 BED=60 CHAMBER=0 TOOL=2"),
    ("M6211 T1 L200 M8 N8 Q220 R240 S220", "M6211 T0 L200 M8 N8 Q220 R240 S220"),  # CANVAS stock firmware
    ("T5", "T5"),                                                           # not in the mapping
    ("; machine_start_gcode = PRINT_START … TOOL={initial_tool}", "; machine_start_gcode = PRINT_START … TOOL={initial_tool}"),
    ("; T1 is only a comment", "; T1 is only a comment"),
    ("G1 X1 Y2 ; T1", "G1 X1 Y2 ; T1"),
    ("M104 S200 T0", "M104 S200 T0"),                                       # hotend index, not a filament
    ("T1 ; change", "T0 ; change"),
])
def test_remap_line(line, expected):
    assert remap_line(line, MAP) == expected


def test_remap_file_keeps_name_and_line_endings(tmp_path):
    g = tmp_path / "flag.gcode"
    g.write_bytes(b"PRINT_START TOOL=0\r\nT1 PURGE_LENGTH=5\r\n; filament_colour = #FF0000;#FFFFFF\r\n")
    out = remap_tools(g, MAP, tmp_path / "out")
    assert out.name == "flag.gcode"
    assert out.read_bytes() == b"PRINT_START TOOL=2\r\nT0 PURGE_LENGTH=5\r\n; filament_colour = #FF0000;#FFFFFF\r\n"


def test_parse_mapping():
    assert parse_mapping({"1": 2, "2": 0}) == MAP and parse_mapping(None) == {}
    for bad in ({"0": 1}, {"17": 1}, {"1": -1}):
        with pytest.raises(ValueError):
            parse_mapping(bad)


def test_lanes_from_afc():
    async def go(afc):
        fake = FakeMoonraker(afc=afc)
        await fake.start()
        try:
            return await get_adapter(PrinterConfig(id="d", type="moonraker", url="http://127.0.0.1:7125")).status()
        finally:
            await fake.stop()
    st = asyncio.run(go(True))
    lanes = st["lanes"]
    assert [(ln["id"], ln["tool"]) for ln in lanes] == [("lane1", 0), ("lane2", 1), ("lane3", 2), ("lane4", 3)]
    assert lanes[1]["color"] == "#E53935" and lanes[1]["material"] == "PLA" and lanes[1]["filament"] == "Elegoo PLA Red"
    assert lanes[0]["in_toolhead"] and not lanes[1]["in_toolhead"]
    assert lanes[3]["loaded"] is False and lanes[3]["color"] is None and lanes[3]["material"] is None
    assert st["state"] == "printing" and st["nozzle"] == 210.1        # the normal status still works
    assert asyncio.run(go(False))["lanes"] == []                      # Klipper without AFC


GCODE = "PRINT_START EXTRUDER=210 BED=60 TOOL=0\nG1 X1 E1\nT1 PURGE_LENGTH=12\nG1 X2 E1\nPRINT_END\n"


def _sliced_job(api, client, monkeypatch, tmp_path):
    _fake_prepare(api, monkeypatch, tmp_path)
    job_id = client.post("/api/jobs", headers=H, json={"link": "https://x.y/flag.3mf", "printer": "dom"}).json()["job"]
    j = _wait(client, job_id, "sliced")
    from pathlib import Path
    Path(j["result"]["gcode"]).write_text(GCODE)
    return job_id


def test_send_with_lanes(api, client, monkeypatch, tmp_path):
    job_id = _sliced_job(api, client, monkeypatch, tmp_path)
    with BackgroundFake(FakeMoonraker(afc=True)) as fake:
        fake.state = "standby"
        # lane4 (T3) is empty: no start
        r = client.post(f"/api/jobs/{job_id}/send", headers=H, json={"start": True, "confirm": True, "lanes": {"1": 3}})
        assert r.status_code == 409 and "lane4" in r.json()["detail"]
        # no lane with T7
        r = client.post(f"/api/jobs/{job_id}/send", headers=H, json={"start": True, "confirm": True, "lanes": {"1": 7}})
        assert r.status_code == 400
        r = client.post(f"/api/jobs/{job_id}/send", headers=H,
                        json={"start": True, "confirm": True, "lanes": {"1": 2, "2": 0}})
        assert r.status_code == 200, r.text
        j = _wait(client, job_id, "started", "sliced")
    assert j["state"] == "started", j
    sent = fake.uploads[0]["data"].decode()
    assert "TOOL=2" in sent and "\nT0 PURGE_LENGTH=12" in sent and "TOOL=0" not in sent
    assert j["result"]["sent"]["tools"] == {"0": 2, "1": 0}
    # the sliced G-code on the server is unchanged (another lane choice needs no re-slicing)
    from pathlib import Path
    assert Path(j["result"]["gcode"]).read_text() == GCODE


def test_lanes_need_a_printer_with_lanes(api, client, monkeypatch, tmp_path):
    job_id = _sliced_job(api, client, monkeypatch, tmp_path)
    with BackgroundFake(FakeMoonraker(afc=False)) as fake:
        fake.state = "standby"
        r = client.post(f"/api/jobs/{job_id}/send", headers=H, json={"start": True, "confirm": True, "lanes": {"1": 1}})
    assert r.status_code == 400 and "no lane" in r.json()["detail"]
