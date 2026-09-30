"""Tilt and scale a model before slicing (per-job options `rotate_x`, `rotate_y`, `scale`).

OrcaSlicer 2.4.2 has `--rotate-x/-y` and `--scale`, but its command line crashes (SIGSEGV in
`PartPlate::check_outside`, no GUI plater) as soon as a transformed object reaches below the bed, which a
rotation about the model origin almost always does. So the server transforms the model itself:

* STL (binary or ASCII) and OBJ: the vertices are rewritten (STL comes out binary).
* 3MF: only the `transform` of each `<build><item>` changes; meshes, colours and project data stay as they
  are. Each item is turned about its own centre and put back on the bed (lowest point z = 0), so OrcaSlicer
  projects (which are not lifted on load) work too.

Rotation around Z is not offered: OrcaSlicer's auto-arrange (`--arrange 1`) turns objects back to their
smallest footprint anyway.
"""
from __future__ import annotations

import math
import re
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
PROD = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
MAIN_MODEL = "3D/3dmodel.model"

Matrix = list[list[float]]   # 3x4, row-major: rows are x', y', z'; column 3 = translation


class TransformError(ValueError):
    pass


def needed(rotate_x: float, rotate_y: float, scale: float) -> bool:
    return bool(rotate_x % 360 or rotate_y % 360 or abs(scale - 1) > 1e-9)


def matrix(rotate_x: float, rotate_y: float, scale: float) -> Matrix:
    """Scale, then rotate about X, then about Y (degrees, right-handed, looking down the axis)."""
    def rot(axis: str, deg: float) -> Matrix:
        a = math.radians(deg)
        c, s = round(math.cos(a), 12), round(math.sin(a), 12)   # exact for multiples of 90°
        if axis == "x":
            return [[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0]]
        return [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0]]
    m = [[scale, 0, 0, 0], [0, scale, 0, 0], [0, 0, scale, 0]]
    return mul(rot("y", rotate_y), mul(rot("x", rotate_x), m))


def mul(a: Matrix, b: Matrix) -> Matrix:
    """a after b (both affine 3x4)."""
    out = []
    for i in range(3):
        row = [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
        row.append(sum(a[i][k] * b[k][3] for k in range(3)) + a[i][3])
        out.append(row)
    return out


def apply(m: Matrix, x: float, y: float, z: float) -> tuple[float, float, float]:
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3])


def transform_model(src: Path, dst_dir: Path, rotate_x: float = 0, rotate_y: float = 0,
                    scale: float = 1) -> Path:
    """Write a transformed copy of `src` into `dst_dir` (same file name) and return its path."""
    if scale <= 0:
        raise TransformError("scale must be positive")
    m = matrix(rotate_x, rotate_y, scale)
    dst_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if ext == ".stl":
        dst = dst_dir / src.name
        _stl(src, dst, m)
    elif ext == ".obj":
        dst = dst_dir / src.name
        _obj(src, dst, m)
    elif ext == ".3mf":
        dst = dst_dir / src.name
        _threemf(src, dst, m)
    else:
        raise TransformError(f"Turning or scaling is not possible for {ext or 'this'} files (only STL, 3MF, OBJ)")
    return dst


# ---------- STL ----------
def _stl(src: Path, dst: Path, m: Matrix) -> None:
    data = src.read_bytes()
    s = math.sqrt(m[0][0] ** 2 + m[1][0] ** 2 + m[2][0] ** 2) or 1.0   # uniform scale factor
    rot = [[v / s for v in row[:3]] + [0.0] for row in m]              # normals: rotation only
    out = bytearray(80)
    tris = _stl_triangles(data)
    out += struct.pack("<I", len(tris))
    pack = struct.Struct("<12fH").pack
    for n, a, b, c in tris:
        out += pack(*apply(rot, *n), *apply(m, *a), *apply(m, *b), *apply(m, *c), 0)
    dst.write_bytes(bytes(out))


def _stl_triangles(data: bytes) -> list[tuple[tuple[float, float, float], ...]]:
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if 84 + count * 50 == len(data):
            return [((v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11]))
                    for v in struct.iter_unpack("<12fH", data[84:84 + count * 50])]
    text = data.decode("utf-8", "replace")
    if "facet" not in text:
        raise TransformError("unreadable STL file")
    num = r"([-+0-9.eE]+)"
    normals = re.findall(rf"facet\s+normal\s+{num}\s+{num}\s+{num}", text)
    verts = [(float(a), float(b), float(c)) for a, b, c in re.findall(rf"vertex\s+{num}\s+{num}\s+{num}", text)]
    if len(verts) != 3 * len(normals):
        raise TransformError("unreadable STL file")
    return [((float(n[0]), float(n[1]), float(n[2])), verts[3 * i], verts[3 * i + 1], verts[3 * i + 2])
            for i, n in enumerate(normals)]


# ---------- OBJ ----------
def _obj(src: Path, dst: Path, m: Matrix) -> None:
    rot = [row[:3] + [0.0] for row in m]
    out = []
    with src.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if parts and parts[0] in ("v", "vn") and len(parts) >= 4:
                try:
                    x, y, z = (float(p) for p in parts[1:4])
                except ValueError:
                    out.append(line)
                    continue
                x, y, z = apply(m if parts[0] == "v" else rot, x, y, z)
                if parts[0] == "vn":
                    length = math.sqrt(x * x + y * y + z * z) or 1.0
                    x, y, z = x / length, y / length, z / length
                rest = " ".join(parts[4:])
                out.append(f"{parts[0]} {x:.6f} {y:.6f} {z:.6f}{' ' + rest if rest else ''}\n")
            else:
                out.append(line)
    dst.write_text("".join(out), encoding="utf-8")


# ---------- 3MF ----------
def _parse_transform(value: str | None) -> Matrix:
    """3MF stores 'm00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32' for row vectors (p' = p·M)."""
    if not value:
        return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
    v = [float(x) for x in value.split()]
    if len(v) != 12:
        raise TransformError("invalid 3MF transform")
    return [[v[0], v[3], v[6], v[9]], [v[1], v[4], v[7], v[10]], [v[2], v[5], v[8], v[11]]]


def _format_transform(m: Matrix) -> str:
    vals = [m[0][0], m[1][0], m[2][0], m[0][1], m[1][1], m[2][1], m[0][2], m[1][2], m[2][2],
            m[0][3], m[1][3], m[2][3]]
    return " ".join(f"{v:.9g}" if abs(v) > 1e-12 else "0" for v in vals)


class _Package:
    def __init__(self, z: zipfile.ZipFile):
        self.z = z
        self.names = {n.lstrip("/"): n for n in z.namelist()}
        self.docs: dict[str, dict[str, ET.Element]] = {}

    def objects(self, part: str) -> dict[str, ET.Element]:
        part = part.lstrip("/")
        if part not in self.docs:
            if part not in self.names:
                raise TransformError(f"3MF part {part} is missing")
            root = ET.fromstring(self.z.read(self.names[part]))
            res = root.find(f"{CORE}resources")
            self.docs[part] = {o.get("id"): o for o in (res.findall(f"{CORE}object") if res is not None else [])}
        return self.docs[part]

    def bounds(self, part: str, object_id: str, m: Matrix, acc: list[float], depth: int = 0) -> None:
        """Grow acc = [minx, miny, minz, maxx, maxy, maxz] by the object's vertices under m."""
        if depth > 16:
            raise TransformError("3MF components nest too deep")
        obj = self.objects(part).get(object_id)
        if obj is None:
            raise TransformError(f"3MF object {object_id} is missing")
        mesh = obj.find(f"{CORE}mesh")
        if mesh is not None:
            verts = mesh.find(f"{CORE}vertices")
            for v in verts if verts is not None else []:
                p = apply(m, float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0)))
                for i in range(3):
                    acc[i] = min(acc[i], p[i])
                    acc[i + 3] = max(acc[i + 3], p[i])
        comps = obj.find(f"{CORE}components")
        for c in comps if comps is not None else []:
            sub = c.get(f"{PROD}path") or c.get("path") or part
            self.bounds(sub, c.get("objectid"), mul(m, _parse_transform(c.get("transform"))), acc, depth + 1)


_ITEM_RE = re.compile(rb"<item\b[^>]*?/?>", re.S)
_TRANSFORM_RE = re.compile(rb'\stransform\s*=\s*"[^"]*"')


def _threemf(src: Path, dst: Path, m: Matrix) -> None:
    with zipfile.ZipFile(src) as z:
        pkg = _Package(z)
        main = next((n for k, n in pkg.names.items() if k.lower() == MAIN_MODEL.lower()), None)
        if main is None:
            raise TransformError("3MF without 3D/3dmodel.model")
        raw = z.read(main)
        root = ET.fromstring(raw)
        build = root.find(f"{CORE}build")
        items = build.findall(f"{CORE}item") if build is not None else []
        if not items:
            raise TransformError("3MF without objects to print")
        new_transforms = []
        for item in items:
            old = _parse_transform(item.get("transform"))
            part = (item.get(f"{PROD}path") or MAIN_MODEL).lstrip("/")
            oid = item.get("objectid")
            before = [math.inf] * 3 + [-math.inf] * 3
            pkg.bounds(part, oid, old, before)
            # turn the item about its own centre, then put it back on the bed at the same x/y
            cx, cy, cz = ((before[i] + before[i + 3]) / 2 for i in range(3))
            to_origin = [[1, 0, 0, -cx], [0, 1, 0, -cy], [0, 0, 1, -cz]]
            t = mul(m, mul(to_origin, old))
            after = [math.inf] * 3 + [-math.inf] * 3
            pkg.bounds(part, oid, t, after)
            t[0][3] += cx
            t[1][3] += cy
            t[2][3] -= after[2]
            new_transforms.append(_format_transform(t))

        # Rewrite only the transform attributes of the <item> tags inside <build>, keeping every other
        # byte (namespaces, Bambu/Orca attributes) as it was.
        start = raw.find(b"<build")
        end = raw.find(b"</build>", start)
        if start < 0 or end < 0:
            raise TransformError("3MF build section not found")
        section = raw[start:end]
        tags = _ITEM_RE.findall(section)
        if len(tags) != len(new_transforms):
            raise TransformError("3MF build items could not be matched")
        it = iter(new_transforms)

        def swap(match: re.Match[bytes]) -> bytes:
            tag = _TRANSFORM_RE.sub(b"", match.group(0))
            value = next(it).encode()
            close = b"/>" if tag.endswith(b"/>") else b">"
            return tag[: -len(close)].rstrip() + b' transform="' + value + b'"' + close
        new_raw = raw[:start] + _ITEM_RE.sub(swap, section) + raw[end:]

        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
            for info in z.infolist():
                out.writestr(info, new_raw if info.filename == main else z.read(info.filename))


def count_objects(path: Path, plate: int = 1) -> int:
    """How many objects OrcaSlicer places for one copy of this model (for counting copies afterwards)."""
    if path.suffix.lower() != ".3mf":
        return 1
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "Metadata/model_settings.config" in names:        # OrcaSlicer / Bambu project: that plate
                root = ET.fromstring(z.read("Metadata/model_settings.config"))
                for p in root.findall("plate"):
                    ids = {md.get("key"): md.get("value") for md in p.findall("metadata")}
                    if ids.get("plater_id") == str(plate):
                        return len(p.findall("model_instance")) or 1
            main = next((n for n in names if n.lower() == MAIN_MODEL.lower()), None)
            if main:
                build = ET.fromstring(z.read(main)).find(f"{CORE}build")
                if build is not None:
                    return len(build.findall(f"{CORE}item")) or 1
    except (zipfile.BadZipFile, ET.ParseError, KeyError):
        pass
    return 1


def placed_objects(result_3mf: Path, plate: int = 1) -> int | None:
    """Objects OrcaSlicer actually put on the sliced plate (Metadata/slice_info.config of --export-3mf)."""
    try:
        with zipfile.ZipFile(result_3mf) as z:
            root = ET.fromstring(z.read("Metadata/slice_info.config"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None
    plates = root.findall("plate")
    for p in plates:
        ids = {md.get("key"): md.get("value") for md in p.findall("metadata")}
        if ids.get("index") == str(plate) or len(plates) == 1:
            return len([o for o in p.findall("object") if o.get("skipped") != "true"])
    return None


_APP_RE = re.compile(rb'<metadata\s+name="(?:Application|OrcaSlicer)"\s*>\s*(BambuStudio-|OrcaSlicer-|\d)')


def is_orca_project(path: Path) -> bool:
    """Same test as OrcaSlicer's `is_bbl_3mf`: Application BambuStudio-/OrcaSlicer- or an OrcaSlicer tag.
    Only such projects keep their plates; `--repetitions` works only for them."""
    if path.suffix.lower() != ".3mf":
        return False
    try:
        with zipfile.ZipFile(path) as z:
            main = next((n for n in z.namelist() if n.lstrip("/").lower() == MAIN_MODEL.lower()), None)
            if main is None:
                return False
            with z.open(main) as fh:
                head = fh.read(64 * 1024)
    except (OSError, zipfile.BadZipFile):
        return False
    return bool(_APP_RE.search(head))
