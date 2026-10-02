"""Exact Klipper print times with klipper_estimator (printshare/klipper_time.py)."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import threading
from pathlib import Path

import pytest
from aiohttp import web

from printshare import klipper_time
from printshare.config import PrinterConfig

GCODE = "; HEADER_BLOCK_START\n; HEADER_BLOCK_END\nG28\nM73 P0 R9\nG1 X10 Y10 F3000\n; estimated printing time (normal mode) = 9m 16s\n"
# Klipper's configfile.settings as Moonraker reports them (only what klipper_estimator reads)
SETTINGS = {"printer": {"kinematics": "corexy", "max_velocity": 500, "max_accel": 20000, "square_corner_velocity": 5.0,
                        "minimum_cruise_ratio": 0.5},
            "extruder": {"instantaneous_corner_velocity": 1.0, "pressure_advance": 0.04, "pressure_advance_smooth_time": 0.04,
                         "max_extrude_only_distance": 50, "max_extrude_only_velocity": 50, "max_extrude_only_accel": 2000,
                         "nozzle_diameter": 0.4, "filament_diameter": 1.75, "max_extrude_cross_section": 50}}


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    """A stand-in for klipper_estimator: records its arguments, rewrites the time like post-process does."""
    log = tmp_path / "args.json"
    exe = tmp_path / "klipper_estimator"
    exe.write_text(f"""#!/usr/bin/env python3
import json, sys, pathlib
args = sys.argv[1:]
calls = json.loads(pathlib.Path({str(log)!r}).read_text()) if pathlib.Path({str(log)!r}).exists() else []
calls.append(args); pathlib.Path({str(log)!r}).write_text(json.dumps(calls))
url = args[args.index("--config_moonraker_url") + 1]
if ":7125" not in url: sys.exit(1)                       # only the second address answers
g = pathlib.Path(args[-1]); g.write_text(g.read_text().replace("9m 16s", "8m 34s"))
""")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("KLIPPER_ESTIMATOR", str(exe))
    return log


def test_post_process_command(tmp_path, fake_bin):
    g = tmp_path / "part.gcode"
    g.write_text(GCODE)
    p = PrinterConfig(id="dom", type="moonraker", url="http://192.168.0.95", api_key="k1")
    assert klipper_time.post_process(g, p, tmp_path / "cfg") is True
    assert "8m 34s" in g.read_text()
    calls = json.loads(fake_bin.read_text())
    assert [c[c.index("--config_moonraker_url") + 1] for c in calls] == ["http://192.168.0.95", "http://192.168.0.95:7125"]
    last = calls[-1]
    assert last[-2:] == ["post-process", str(g)] and "--config_moonraker_ignore_error" in last
    assert last[last.index("--config_moonraker_api_key") + 1] == "k1"
    assert last[last.index("--config_moonraker_cache_file") + 1] == str(tmp_path / "cfg" / "klipper_estimator" / "dom.json")


def test_only_reachable_klipper_printers(tmp_path, fake_bin, monkeypatch):
    g = tmp_path / "part.gcode"
    g.write_text(GCODE)
    assert klipper_time.post_process(g, PrinterConfig(id="cc", type="elegoo_sdcp", host="x"), tmp_path) is False
    assert klipper_time.post_process(g, PrinterConfig(id="cloud", type="moonraker"), tmp_path) is False   # no address
    assert not fake_bin.exists() and "9m 16s" in g.read_text()
    monkeypatch.setenv("KLIPPER_ESTIMATOR", str(tmp_path / "missing"))
    monkeypatch.setattr(klipper_time, "DEFAULT_BIN", str(tmp_path / "missing"))
    monkeypatch.setattr(klipper_time.shutil, "which", lambda name: None)
    assert klipper_time.binary() is None
    assert klipper_time.post_process(g, PrinterConfig(id="d", type="moonraker", url="http://x:7125"), tmp_path) is False


def _real_binary():
    return klipper_time.binary() if os.environ.get("KLIPPER_ESTIMATOR") or Path(klipper_time.DEFAULT_BIN).exists() else None


@pytest.mark.skipif(_real_binary() is None, reason="klipper_estimator not installed (it is in the Docker image)")
def test_real_estimator_and_saved_limits(tmp_path):
    from .test_printshare import ORCA_ROOT  # noqa: F401  (same environment as the slicing tests)
    port = 8644

    async def query(request):
        return web.json_response({"result": {"eventtime": 1, "status": {"configfile": {"settings": SETTINGS}}}})
    loop = asyncio.new_event_loop()
    runner = web.AppRunner(web.Application())
    runner.app.router.add_get("/printer/objects/query", query)
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", port).start())
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    g = tmp_path / "moves.gcode"
    # 100 mm square at 300 mm/s (F18000) ten times: Klipper's acceleration makes it take longer than distance/speed
    lines = ["G90", "M83", "G28", "G1 Z0.2 F600"] + ["G1 X110 Y10 E1 F18000\nG1 X110 Y110 E1\nG1 X10 Y110 E1\nG1 X10 Y10 E1"] * 10
    g.write_text("; estimated printing time (normal mode) = 1m 0s\n" + "\n".join(lines) + "\n")
    p = PrinterConfig(id="vor", type="moonraker", url=f"http://127.0.0.1:{port}")
    try:
        assert klipper_time.post_process(g, p, tmp_path) is True
        first = g.read_text()
        assert "Processed by klipper_estimator" in first and (tmp_path / "klipper_estimator" / "vor.json").is_file()
    finally:                               # switch the "printer" off: close the port, then stop the loop
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
        t.join(5)
    # printer switched off: the saved limits are used
    g.write_text("; estimated printing time (normal mode) = 1m 0s\n" + "\n".join(lines) + "\n")
    assert klipper_time.post_process(g, p, tmp_path) is True
    assert g.read_text().split("estimated printing time")[1][:30] == first.split("estimated printing time")[1][:30]
