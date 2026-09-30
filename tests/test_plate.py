"""Plate options per job: copies, tilt, scale, automatic orientation (0.14.0)."""
from __future__ import annotations

import math
import re
import struct
import zipfile
from pathlib import Path

import pytest

from printshare import transform
from printshare.config import JobOptions, PrinterConfig, SlicingConfig

from .test_printshare import _settings, _two_colour_3mf, needs_orca


def _box_stl(path: Path, x: float, y: float, z: float) -> Path:
    import trimesh
    trimesh.creation.box(extents=(x, y, z)).export(path)
    return path


def _stl_bounds(path: Path) -> list[float]:
    tris = transform._stl_triangles(path.read_bytes())
    pts = [p for t in tris for p in t[1:]]
    return [min(p[i] for p in pts) for i in range(3)] + [max(p[i] for p in pts) for i in range(3)]


def _size(b: list[float]) -> tuple[float, ...]:
    return tuple(round(b[i + 3] - b[i], 3) for i in range(3))


# ---------- options ----------
def test_plate_options_apply_and_defaults():
    s = JobOptions(copies=3, rotate_x=90, scale=150, orient=True).apply(SlicingConfig())
    assert (s.copies, s.rotate_x, s.rotate_y, s.scale, s.auto_orient) == (3, 90, 0, 1.5, True)
    d = JobOptions().apply(SlicingConfig(auto_orient=True))
    assert (d.copies, d.rotate_x, d.scale, d.auto_orient) == (1, 0, 1.0, True)   # printer setting kept


@pytest.mark.parametrize("opts", [dict(copies=0), dict(copies=51), dict(rotate_x=400), dict(rotate_y=-361),
                                  dict(scale=5), dict(scale=1001), dict(orient=True, rotate_x=90)])
def test_plate_options_out_of_range(opts):
    with pytest.raises(ValueError):
        JobOptions(**opts).check_plate()


# ---------- model transformation ----------
def test_stl_tilt_and_scale(tmp_path):
    src = _box_stl(tmp_path / "bar.stl", 120, 20, 10)
    out = transform.transform_model(src, tmp_path / "t", rotate_x=90)
    assert _size(_stl_bounds(out)) == (120, 10, 20)
    out = transform.transform_model(src, tmp_path / "t2", rotate_y=90, scale=0.5)
    assert _size(_stl_bounds(out)) == (5, 10, 60)
    assert src.read_bytes() != out.read_bytes() and _size(_stl_bounds(src)) == (120, 20, 10)   # source untouched


def test_ascii_stl_and_obj(tmp_path):
    ascii_stl = tmp_path / "a.stl"
    ascii_stl.write_text("solid a\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 5 0\n"
                         "endloop\nendfacet\nendsolid a\n")
    out = transform.transform_model(ascii_stl, tmp_path / "t", rotate_x=90)
    tris = transform._stl_triangles(out.read_bytes())
    assert len(tris) == 1
    n, a, b, c = tris[0]
    assert [round(v, 6) for v in n] == [0, -1, 0] and [round(v, 6) for v in c] == [0, 0, 5]
    obj = tmp_path / "m.obj"
    obj.write_text("# test\nv 1 2 3\nvn 0 0 1\nf 1 1 1\n")
    lines = transform.transform_model(obj, tmp_path / "o", scale=2).read_text().splitlines()
    assert lines[0] == "# test" and lines[1] == "v 2.000000 4.000000 6.000000"
    assert lines[2] == "vn 0.000000 0.000000 1.000000" and lines[3] == "f 1 1 1"


def test_step_cannot_be_turned(tmp_path):
    step = tmp_path / "m.step"
    step.write_text("ISO-10303-21;")
    with pytest.raises(transform.TransformError):
        transform.transform_model(step, tmp_path / "t", rotate_x=90)


def _plain_3mf(path: Path) -> Path:
    """Two 10x20x30 boxes as plain 3MF (no slicer metadata), the second one moved."""
    verts = [(x, y, z) for x in (0, 10) for y in (0, 20) for z in (0, 30)]
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in
                [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
                 (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)])
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources><object id="1" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles>'
             '</mesh></object></resources><build><item objectid="1"/>'
             '<item objectid="1" transform="1 0 0 0 1 0 0 0 1 50 60 0" printable="1" /></build></model>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                   '<Default Extension="png" ContentType="image/png"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/thumbnail.png", b"png")
    return path


def _item_bounds(path: Path) -> list[list[float]]:
    with zipfile.ZipFile(path) as z:
        pkg = transform._Package(z)
        from xml.etree import ElementTree as ET
        root = ET.fromstring(z.read("3D/3dmodel.model"))
        out = []
        for item in root.find(f"{transform.CORE}build"):
            acc = [math.inf] * 3 + [-math.inf] * 3
            pkg.bounds("3D/3dmodel.model", item.get("objectid"), transform._parse_transform(item.get("transform")), acc)
            out.append([round(a, 4) for a in acc])
        return out


def test_3mf_items_turn_in_place_and_stay_on_the_bed(tmp_path):
    src = _plain_3mf(tmp_path / "two.3mf")
    out = transform.transform_model(src, tmp_path / "t", rotate_y=90)
    before, after = _item_bounds(src), _item_bounds(out)
    for b, a in zip(before, after):
        assert _size(a) == (30, 20, 10)                       # lying on its side now
        assert a[2] == 0                                       # on the bed
        assert (a[0] + a[3]) / 2 == pytest.approx((b[0] + b[3]) / 2)   # same place on the plate
        assert (a[1] + a[4]) / 2 == pytest.approx((b[1] + b[4]) / 2)
    with zipfile.ZipFile(src) as zs, zipfile.ZipFile(out) as zo:
        assert zo.namelist() == zs.namelist() and zo.read("Metadata/thumbnail.png") == b"png"
        assert zo.read("_rels/.rels") == zs.read("_rels/.rels")
        text = zo.read("3D/3dmodel.model").decode()
        assert 'printable="1"' in text and text.count("transform=") == 2
        assert text.split("<build>")[0] == zs.read("3D/3dmodel.model").decode().split("<build>")[0]


def test_counting_objects(tmp_path):
    assert transform.count_objects(tmp_path / "a.stl") == 1
    assert transform.count_objects(_plain_3mf(tmp_path / "two.3mf")) == 2
    assert not transform.is_orca_project(tmp_path / "two.3mf")
    info = tmp_path / "r.3mf"
    with zipfile.ZipFile(info, "w") as z:
        z.writestr("Metadata/slice_info.config",
                   '<config><plate><metadata key="index" value="1"/><object identify_id="1" skipped="false"/>'
                   '<object identify_id="2" skipped="false"/><object identify_id="3" skipped="true"/></plate></config>')
    assert transform.placed_objects(info) == 2
    assert transform.placed_objects(tmp_path / "missing.3mf") is None


# ---------- real OrcaSlicer ----------
def _slice(tmp_path, model: Path, **opts):
    from printshare.slicer import Slicer
    s = _settings(tmp_path)
    printer = PrinterConfig(id="cc", type="elegoo_sdcp", host="127.0.0.1")
    return Slicer(s).slice(model, printer, tmp_path / "out", JobOptions(**opts).apply(printer.slicing))


def _objects(gcode: Path) -> int:
    return len(re.findall(r"^EXCLUDE_OBJECT_DEFINE ", gcode.read_text(), re.M))


@needs_orca
def test_copies_of_an_stl(tmp_path):
    res = _slice(tmp_path, _box_stl(tmp_path / "cube.stl", 20, 20, 20), copies=4)
    assert res.copies == 4 and _objects(res.gcode_path) == 4, res.log[-2000:]


@needs_orca
def test_too_many_copies_fit_as_many_as_possible(tmp_path):
    res = _slice(tmp_path, _box_stl(tmp_path / "bar.stl", 120, 20, 10), copies=30)
    assert res.copies is not None and 2 <= res.copies < 30, res.log[-2000:]
    assert _objects(res.gcode_path) == res.copies


@needs_orca
def test_copies_of_a_plain_3mf(tmp_path):
    res = _slice(tmp_path, _plain_3mf(tmp_path / "two.3mf"), copies=3)
    assert res.copies == 3 and _objects(res.gcode_path) == 6, res.log[-2000:]


@needs_orca
def test_tilt_and_scale_change_the_height(tmp_path):
    bar = _box_stl(tmp_path / "bar.stl", 120, 20, 10)
    flat = _slice(tmp_path / "a", bar)
    tilted = _slice(tmp_path / "b", bar, rotate_x=90)
    bigger = _slice(tmp_path / "c", bar, scale=200)
    assert flat.layers and tilted.layers and bigger.layers
    assert tilted.layers == pytest.approx(2 * flat.layers, abs=2), (flat.layers, tilted.layers)
    assert bigger.layers == pytest.approx(2 * flat.layers, abs=2), (flat.layers, bigger.layers)
    assert flat.copies is None


@needs_orca
def test_copies_and_tilt_of_an_orca_project(tmp_path):
    project = _two_colour_3mf(tmp_path)
    assert transform.is_orca_project(project) and transform.count_objects(project) == 2
    opts = dict(filaments=["Elegoo PLA @ECC", "Elegoo PLA @ECC"])
    one = _slice(tmp_path / "a", project, **opts)
    two = _slice(tmp_path / "b", project, copies=2, **opts)
    assert two.copies == 2 and _objects(two.gcode_path) == 4, two.log[-2000:]
    assert [f["grams"] for f in two.filaments] == pytest.approx([2 * f["grams"] for f in one.filaments], rel=0.1)
    tilted = _slice(tmp_path / "c", project, rotate_y=90, **opts)       # 20x20x10 boxes stand up
    assert tilted.layers == pytest.approx(2 * one.layers, abs=2), (one.layers, tilted.layers)
    assert "\nT1" in tilted.gcode_path.read_text()                      # colours survive


def test_stl_binary_writer_roundtrip(tmp_path):
    src = tmp_path / "t.stl"
    src.write_bytes(bytes(80) + struct.pack("<I", 1) + struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0))
    out = transform.transform_model(src, tmp_path / "o", scale=3)
    assert _size(_stl_bounds(out)) == (3, 3, 0)
