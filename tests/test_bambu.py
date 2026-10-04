"""Bambu Lab in LAN-only mode (printers/bambu.py): report → status/lanes from a real P1S report, the wrapped 3MF, the
start command with ams_mapping, the bridge registry entry. The MQTT connection is replaced by a fake."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import threading
import zipfile
from pathlib import Path

import pytest

from printshare.bridge import registry
from printshare.config import PrinterConfig, Settings
from printshare.printers import bambu, get_adapter
from printshare import pipeline

DATA = Path(__file__).parent / "data"
REPORT = json.loads((DATA / "bambu_p1s_report.json").read_text())["print"]
CONE = DATA / "orca_cone.gcode"


def two_colour(tmp_path: Path) -> Path:
    g = tmp_path / "two.gcode"
    g.write_text(CONE.read_text().replace("; filament_type = PLA", "; filament_type = PLA;PETG")
                 .replace("; filament_colour = #F2754E", "; filament_colour = #F2754E;#00FF00") + "T1\n")
    return g


def test_status_and_lanes_from_a_real_p1s_report():
    st = bambu.status_from(REPORT)
    assert st["state"] == "standby" and st["speed"] == 100 and st["lights"] == {"light": False}
    assert st["heaters"]["bed"]["actual"] == REPORT["bed_temper"]
    lanes = st["lanes"]
    assert [x["id"] for x in lanes] == ["A1", "A2", "A3", "A4"]
    a1, a2, a3 = lanes[0], lanes[1], lanes[2]
    assert a1["material"] == "PETG" and a1["color"] == "#898989" and a1["loaded"] and not a1["in_toolhead"]
    assert a2["in_toolhead"] and a2["tool"] == 1              # tray_now "1"
    assert not a3["loaded"] and a3["material"] is None          # tray_exist_bits "b" = trays 0, 1, 3


def test_states_and_merge():
    run = bambu.status_from({"gcode_state": "RUNNING", "mc_percent": 42, "mc_remaining_time": 7, "subtask_name": "cube"})
    assert run["state"] == "printing" and run["progress"] == 42 and run["time_remaining_s"] == 420 and run["file"] == "cube"
    assert bambu.status_from({"gcode_state": "FAILED", "print_error": 50348044})["state"] == "cancelled"
    assert bambu.status_from({"gcode_state": "FAILED", "print_error": 83935249})["state"] == "error"
    assert bambu.status_from({"gcode_state": "FINISH"})["state"] == "complete"
    # the P1 sends only what changed: trays are merged by id
    state = json.loads(json.dumps(REPORT))
    bambu.merge(state, {"ams": {"tray_now": "0", "ams": [{"id": "0", "tray": [{"id": "2", "tray_type": "PLA",
                                                                              "tray_color": "FF0000FF"}]}]},
                        "nozzle_temper": 210})
    assert state["nozzle_temper"] == 210 and state["bed_temper"] == REPORT["bed_temper"]
    trays = state["ams"]["ams"][0]["tray"]
    assert len(trays) == 4 and trays[2]["tray_type"] == "PLA" and trays[0]["tray_type"] == "PETG"


def test_wrapped_3mf_and_mapping(tmp_path):
    g = two_colour(tmp_path)
    data = bambu.wrap_3mf(g, "two.gcode.3mf")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        gcode = z.read("Metadata/plate_1.gcode")
        assert gcode == g.read_bytes()
        assert z.read("Metadata/plate_1.gcode.md5").decode() == hashlib.md5(gcode).hexdigest().upper()
        info = z.read("Metadata/slice_info.config").decode()
        assert 'type="PETG" color="#00FF00"' in info and "3D/3dmodel.model" in z.namelist()
    assert bambu.ams_mapping(g, None, REPORT) == [0, 1]
    assert bambu.ams_mapping(g, {0: 3, 1: 0}, REPORT) == [3, 0]
    assert bambu.ams_mapping(CONE, None, REPORT) == [1]          # one colour: the tray in the toolhead
    assert bambu.remote_name(Path("Ring – v2 (1).gcode")) == "Ring_v2_1.gcode.3mf"
    assert bambu.machine_for("01P00C0000000") == "Bambu Lab P1S 0.4 nozzle" and bambu.machine_for("ZZZ") is None


class FakeLink:
    """Accepts a print like the P1S in LAN-only mode (gcode_state → PREPARE); refuse=True: ignores it (cloud mode)."""

    def __init__(self) -> None:
        self.ready = threading.Event()
        self.ready.set()
        self.error = None
        self.sent: list[dict] = []
        self.replies: dict = {}
        self.report = json.loads(json.dumps(REPORT))
        self.refuse = False

    def snapshot(self):
        return json.loads(json.dumps(self.report))

    def publish(self, payload):
        self.sent.append(payload)
        cmd = payload.get("print") or {}
        if cmd.get("command") == "project_file" and not self.refuse:
            self.report.update(gcode_state="PREPARE", subtask_name=cmd["subtask_name"])


@pytest.fixture
def fake(monkeypatch):
    link = FakeLink()
    uploads: list[tuple[str, bytes]] = []
    monkeypatch.setattr(bambu, "link", lambda host, serial, code: link)
    monkeypatch.setattr(bambu, "read_serial", lambda host, timeout=5.0: ("01P00C0000000", True))
    monkeypatch.setattr(bambu, "upload", lambda host, code, name, data: uploads.append((name, data)))
    return link, uploads


def test_send_through_the_pipeline_keeps_the_gcode_and_maps_trays(tmp_path, fake):
    link, uploads = fake
    g = two_colour(tmp_path)
    cfg = PrinterConfig(id="p1s", type="bambu_lan", host="192.168.1.53", password="12345678")
    settings = Settings(printers=[cfg], work_dir=str(tmp_path), gcode_dir=str(tmp_path))
    result = pipeline.JobResult(printer="p1s", source_file="two.stl", gcode=str(g), print_time=None, filament_g=None,
                                filament_m=None)
    sent = asyncio.run(pipeline.send_job(settings, result, start=True, tools={0: 3, 1: 0}, leveling=False))
    assert sent["file"] == "two.gcode" and sent["started"] and sent["ams_mapping"] == [3, 0]
    name, data = uploads[0]
    assert name == "two.gcode.3mf"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.read("Metadata/plate_1.gcode") == g.read_bytes()     # not rewritten: the mapping does it
    cmd = link.sent[-1]["print"]
    assert cmd["command"] == "project_file" and cmd["url"] == "file:///sdcard/two.gcode.3mf"
    assert cmd["ams_mapping"] == [3, 0] and cmd["use_ams"] is True and cmd["bed_levelling"] is False
    assert cmd["subtask_name"] == "two"            # what status() reports as the file → job tracking matches


def test_upload_only_and_controls(fake, tmp_path):
    link, uploads = fake
    a = get_adapter(PrinterConfig(id="p1s", type="bambu_lan", host="192.168.1.53", password="12345678"))
    out = asyncio.run(a.send(CONE, start=False))
    assert out == {"uploaded": "orca_cone.gcode.3mf", "file": "orca_cone.gcode", "started": False} and not link.sent
    asyncio.run(a.control("cancel"))
    asyncio.run(a.adjust("heater", "nozzle", 999))
    asyncio.run(a.adjust("fan", "part", 50))
    asyncio.run(a.adjust("light", "light", True))
    asyncio.run(a.adjust("speed", "x", 124))
    cmds = [list(p.values())[0] for p in link.sent]
    assert cmds[0]["command"] == "stop"
    assert cmds[1]["param"] == "M104 S300\n" and cmds[2]["param"] == "M106 P1 S128\n"
    assert cmds[3]["command"] == "ledctrl" and cmds[3]["led_mode"] == "on"
    assert cmds[4] == {"command": "print_speed", "param": "3"}
    with pytest.raises(ValueError):
        asyncio.run(a.adjust("speed", "x", 77))


def test_bridge_registry_entry():
    cfg = registry.build({"type": "bambu_lan", "name": "P1S", "machine": "Bambu Lab P1S 0.4 nozzle"},
                         {"address": "192.168.1.53", "password": "12345678"}, "p1s")
    assert cfg["host"] == "192.168.1.53" and cfg["password"] == "12345678" and "url" not in cfg
    assert cfg["slicing"]["machine"] == "Bambu Lab P1S 0.4 nozzle"
    with pytest.raises(ValueError):
        get_adapter(PrinterConfig(id="x", type="bambu_lan", host="192.168.1.53"))       # no access code


def test_subnet_hint_from_the_app():
    from printshare.bridge.discovery import subnet_hint
    assert subnet_hint("192.168.86.0/24") == "192.168.86.0/24"
    assert subnet_hint("192.168.86.23/24") == "192.168.86.0/24"
    assert subnet_hint("10.0.0.0/8") is None          # too big to scan
    assert subnet_hint("8.8.8.0/24") is None          # not a home network
    assert subnet_hint("nonsense") is None and subnet_hint(None) is None


def test_a_start_the_printer_ignores_is_an_error(fake, tmp_path, monkeypatch):
    link, _ = fake
    link.refuse = True                                # cloud mode: the command is dropped silently
    monkeypatch.setattr(bambu, "START_TIMEOUT_S", 1.5)
    a = get_adapter(PrinterConfig(id="p1s", type="bambu_lan", host="192.168.1.53", password="12345678"))
    with pytest.raises(bambu.BambuError, match="LAN-only"):
        asyncio.run(a.send(CONE, start=True))
    link.refuse = False
    link.replies["project_file"] = {"result": "fail", "reason": "busy", "_at": 9e12}
    with pytest.raises(bambu.BambuError, match="busy"):
        asyncio.run(a.send(CONE, start=True))
