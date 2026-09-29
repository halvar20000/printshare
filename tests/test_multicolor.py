"""Multicolour groundwork (MA-04): colours of 3MF projects, per-colour presets, download cache."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from printshare import model_info
from printshare.config import JobOptions, PrinterConfig, Settings, SlicingConfig
from printshare.fetch import RemoteFile
from printshare.pipeline import fetch_model
from printshare.slicer import Slicer, filament_grams

MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources><object id="1" type="model"><mesh><vertices>
  <vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="0"/><vertex x="0" y="0" z="10"/>
 </vertices><triangles>
  <triangle v1="0" v2="2" v3="1"{paint}/><triangle v1="0" v2="1" v3="3"/><triangle v1="1" v2="2" v3="3"/><triangle v1="0" v2="3" v3="2"/>
 </triangles></mesh></object></resources>
 <build><item objectid="1"/></build>
</model>"""


def orca_3mf(path: Path, colours: list[str], extruders: list[int], painted: bool = False) -> Path:
    """Project 3MF like OrcaSlicer / Bambu Studio write it."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", MODEL.format(paint=' paint_color="4"' if painted else ""))
        z.writestr("Metadata/project_settings.config", json.dumps({
            "filament_colour": colours, "filament_type": ["PLA"] * len(colours),
            "filament_settings_id": [f"Bambu PLA Basic @BBL X1C {i}" for i in range(len(colours))]}))
        parts = "".join(f'<part id="{i + 1}" subtype="normal_part"><metadata key="extruder" value="{e}"/></part>'
                        for i, e in enumerate(extruders))
        z.writestr("Metadata/model_settings.config",
                   f'<?xml version="1.0"?><config><object id="1"><metadata key="extruder" value="{extruders[0]}"/>'
                   f"{parts}</object></config>")
    return path


def prusa_3mf(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", MODEL.format(paint=""))
        z.writestr("Metadata/Slic3r_PE.config",
                   '; extruder_colour = "";""\n; filament_colour = "#FF8000";"#db5182"\n'
                   '; filament_type = PLA;PETG\n; filament_settings_id = "Prusament PLA";"Prusament PETG"\n')
        z.writestr("Metadata/Slic3r_PE_model.config",
                   '<?xml version="1.0"?><config><object id="1"><metadata type="object" key="extruder" value="1"/>'
                   '<volume firstid="0" lastid="3"><metadata type="volume" key="extruder" value="2"/></volume>'
                   "</object></config>")
    return path


# ---------- colours of a model ----------
def test_orca_project_colours_and_used_filaments(tmp_path):
    info = model_info.inspect(orca_3mf(tmp_path / "a.3mf", ["#FF0000FF", "#00ae42", "#FFFFFF"], [1, 3]))
    assert [f["color"] for f in info["filaments"]] == ["#FF0000", "#00AE42", "#FFFFFF"]
    assert info["used"] == [1, 3] and info["painted"] is False and info["source"] == "orca"
    assert info["filaments"][0]["type"] == "PLA"


def test_painted_model_uses_all_filaments(tmp_path):
    info = model_info.inspect(orca_3mf(tmp_path / "p.3mf", ["#FF0000", "#0000FF"], [1], painted=True))
    assert info["painted"] and info["used"] == [1, 2]


def test_prusa_project(tmp_path):
    info = model_info.inspect(prusa_3mf(tmp_path / "prusa.3mf"))
    assert [f["color"] for f in info["filaments"]] == ["#FF8000", "#DB5182"]   # empty extruder colours ignored
    assert [f["type"] for f in info["filaments"]] == ["PLA", "PETG"]
    assert info["used"] == [1, 2] and info["source"] == "prusa"


def test_single_colour_files(tmp_path):
    stl = tmp_path / "a.stl"
    stl.write_text("solid a\nendsolid a\n")
    assert model_info.inspect(stl)["filaments"] == []
    plain = tmp_path / "plain.3mf"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("3D/3dmodel.model", MODEL.format(paint=""))
    assert model_info.inspect(plain)["filaments"] == []
    broken = tmp_path / "broken.3mf"
    broken.write_text("not a zip")
    assert model_info.inspect(broken)["filaments"] == []


# ---------- presets per colour ----------
@pytest.fixture
def library(tmp_path):
    root = tmp_path / "profiles" / "V"
    for kind, presets in {
        "machine": [{"name": "M", "printable_area": ["0x0", "200x0", "200x200", "0x200"]}],
        "process": [{"name": "P", "compatible_printers": ["M"]}],
        "filament": [{"name": "PLA A", "compatible_printers": ["M"], "filament_colour": ["#FFFFFF"]},
                     {"name": "PETG B", "compatible_printers": ["M"], "filament_colour": ["#FFFFFF"]}],
    }.items():
        (root / kind).mkdir(parents=True)
        for p in presets:
            (root / kind / f"{p['name']}.json").write_text(json.dumps(p))
    return tmp_path / "profiles"


def test_one_filament_preset_per_colour(tmp_path, library):
    s = Settings(orca_profiles_dir=str(library), work_dir=str(tmp_path / "w"), gcode_dir=str(tmp_path / "g"))
    printer = PrinterConfig(id="x", type="moonraker", url="http://a",
                            slicing=SlicingConfig(machine="M", process="P", filament="PLA A"))
    slicing = JobOptions(filaments=["PETG B", None, "PLA A"]).apply(printer.slicing)
    assert slicing.filaments == ["PETG B", "PLA A", "PLA A"]
    m, p, fs = Slicer(s).build_presets(printer, tmp_path, slicing, colors=["#FF0000", "#00FF00", "#0000FF"])
    loaded = [json.loads(f.read_text()) for f in fs]
    assert [f["name"] for f in loaded] == ["PETG B", "PLA A", "PLA A"]
    assert [f["filament_colour"] for f in loaded] == [["#FF0000"], ["#00FF00"], ["#0000FF"]]
    # model with more colours than chosen materials: the rest get the default material
    _, _, fs = Slicer(s).build_presets(printer, tmp_path, printer.slicing, colors=["#111111", "#222222"])
    assert [json.loads(f.read_text())["name"] for f in fs] == ["PLA A", "PLA A"]
    # single colour stays one preset
    assert len(Slicer(s).build_presets(printer, tmp_path, printer.slicing)[2]) == 1


def test_filament_grams(tmp_path):
    g = tmp_path / "a.gcode"
    g.write_text("G1 X1\n; filament used [mm] = 100.00, 200.00\n; filament used [g] = 1.23, 4.56\n")
    assert filament_grams(g) == [1.23, 4.56]
    g.write_text("G1 X1\n")
    assert filament_grams(g) == []


# ---------- download cache ----------
def test_download_is_cached(tmp_path, monkeypatch):
    calls = []

    class FakeFetcher:
        def __init__(self, token=""):
            pass

        def list_files(self, link):
            return [RemoteFile("printables", "42", "7", "part.3mf", 10)]

        def download(self, f, dest):
            calls.append(f.file_id)
            dest.mkdir(parents=True, exist_ok=True)
            return orca_3mf(dest / f.name, ["#FF0000", "#0000FF"], [1, 2])

    monkeypatch.setattr("printshare.pipeline.Fetcher", FakeFetcher)
    s = Settings(work_dir=str(tmp_path / "w"), gcode_dir=str(tmp_path / "g"))
    Path(s.work_dir).mkdir()
    _, first = fetch_model(s, "https://www.printables.com/model/42-x")
    _, second = fetch_model(s, "https://www.printables.com/model/42-x")
    assert first == second and first.is_file() and calls == ["7"]
    from printshare.pipeline import inspect_model
    info = inspect_model(s, "https://www.printables.com/model/42-x")
    assert info["file"] == "part.3mf" and info["used"] == [1, 2] and calls == ["7"]
