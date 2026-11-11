"""The designer's Rhino model as Sida reads it: a snapshot the Rhino plugin sends, and figures from it.

The plugin (rhino-plugin/, a C# RhinoCommon plugin) only carries and captures: for every
visible object on a layer the designer gave a meaning it sends what Rhino itself computed
(the volume, the footprint on the ground, the area at every floor height) and a few view
captures. Everything that is a rule or a judgement lives here, in Python, where the tests
are: which meanings count as building, how the footprint of many objects is one coverage,
and what the ratios are against the site area from the site facts. Sida never guesses a
number: an object Rhino could not measure (open geometry) stays "unmeasured", and without a
site area there is no coverage or FAR (the same rule as the massing schemes on the table).

A snapshot is saved whole under the project, `rhino/snapshots/<id>/` (snapshot.json and the
view PNGs), newest MAX_SNAPSHOTS kept, and the newest one is also laid on the drafting table
as the "라이노 작업" paper (board.rhino_paper): it is the designer's own work, so it goes on
the table and not in the AI section. The experts get a short summary of the newest snapshot
(prompt_text) through hooks.py; the geometry itself is never sent to a model.

Snapshot v1 (`schema: 1`), as the plugin sends it, in metres in the table's frame (the site's
middle is the origin, x east, y north, z up: the frame the 3dm export is in, so a model the
plugin pulled from Sida sends its work back in the same place):

    {"schema": 1,
     "rhino": {"version": "8.12", "file": "studio.3dm", "units": "m"},
     "origin": {"lon": 126.97, "lat": 37.56, "matches_project": true},      (optional)
     "layers": [{"path": "Program::Housing", "meaning": "housing", "color": "#c86432", "floor_height": 3.0}],
     "objects": [{"id": "<rhino guid>", "sida_id": "mass-a:0" | null, "layer": "Program::Housing",
                  "name": "", "volume": 4200.0 | null, "height": 12.0 | null, "base": 0.0 | null,
                  "footprint": [[x, y], ...] | [[[x, y], ...], ...] | null, "floors": [{"z": 0.0, "area": 240.0}, ...],
                  "mesh": {"v": [[x, y, z], ...], "f": [[a, b, c], ...]}}],                 (optional)
     "views": [{"kind": "plan", "file": "plan.png"}, {"kind": "axo", "file": "axo.png"}]}

A footprint is one ring or several: a ring inside another is a hole (a courtyard) and a ring
apart is another piece, read by the even-odd rule; it is kept as a list of rings. `base` is
the z of the object's lowest point, so the height of the whole is the highest top above the
lowest base and not the tallest single object.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime
from pathlib import Path

from sida.storage import atomic_write_text

SCHEMA = 1
SNAPSHOT_DIR = Path("rhino") / "snapshots"
MAX_SNAPSHOTS = 30
MAX_LAYERS = 500
MAX_OBJECTS = 2000
MAX_FLOORS = 200
MAX_OUTLINE = 500
MAX_RINGS = 50  # pieces and holes of one footprint
MAX_MESH_VERTICES = 20000  # a larger mesh is dropped from the snapshot; the figures stay
MAX_VIEWS = 8
MAX_VIEW_BYTES = 10 * 1024 * 1024
MAX_TEXT = 200
PNG = b"\x89PNG\r\n\x1a\n"
VIEW_FILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}\.png")
VIEW_KINDS = ("plan", "axo", "persp", "elevation", "section", "eye")
SNAPSHOT_ID = re.compile(r"\d{8}-\d{6}-\d{4}")  # time taken, then a count within that second
COLOR = re.compile(r"#[0-9a-fA-F]{6}")

# What a layer may mean (the designer picks it in the plugin's panel; nothing is inferred).
# `built` meanings count towards floor area, footprint and the ratios; the others are context.
MEANINGS: dict[str, dict] = {
    "housing": {"word": "주거", "built": True},
    "commercial": {"word": "상업", "built": True},
    "office": {"word": "업무", "built": True},
    "culture": {"word": "문화·교육", "built": True},
    "core": {"word": "코어·설비", "built": True},
    "other": {"word": "기타 용도", "built": True},
    "outdoor": {"word": "외부 공간", "built": False},
    "surroundings": {"word": "주변 건물", "built": False},
    "site": {"word": "대지 경계", "built": False},
    "ignore": {"word": "제외", "built": False},
}
BUILT = tuple(code for code, m in MEANINGS.items() if m["built"])


# ---------------------------------------------------------------------------
# Checking what the plugin sent
# ---------------------------------------------------------------------------


def _number(value, what: str, *, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a number")
    if low is not None and value < low:
        raise ValueError(f"{what} must be at least {low:g}")
    if high is not None and value > high:
        raise ValueError(f"{what} must be at most {high:g}")
    return float(value)


def _text(value, what: str, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text")
    return value.strip()[:limit]


def _points(raw, what: str, dims: int, limit: int) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) > limit:
        raise ValueError(f"{what} must be a list of at most {limit} points")
    out = []
    for i, point in enumerate(raw):
        if not isinstance(point, (list, tuple)) or len(point) != dims:
            raise ValueError(f"{what}[{i}] must have {dims} coordinates")
        out.append([round(_number(c, f"{what}[{i}]"), 4) for c in point])
    return out


def _rings(raw, what: str) -> list[list[list[float]]]:
    """A footprint as rings: the plugin sends one ring ([[x, y], ...]) or several."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{what} must be a ring of points or a list of rings")
    first = raw[0]
    single = not (isinstance(first, (list, tuple)) and first and isinstance(first[0], (list, tuple)))
    rings = [raw] if single else raw
    if len(rings) > MAX_RINGS:
        raise ValueError(f"{what} must have at most {MAX_RINGS} rings")
    out = []
    for i, ring in enumerate(rings):
        outline = _points(ring, what if single else f"{what}[{i}]", 2, MAX_OUTLINE)
        if len(outline) < 3:
            raise ValueError(f"{what} needs at least 3 points in a ring")
        out.append(outline)
    return out


def _layer(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"layers[{index}] must be an object")
    path = _text(raw.get("path"), f"layers[{index}].path")
    if not path:
        raise ValueError(f"layers[{index}] needs a path")
    meaning = _text(raw.get("meaning"), f"layers[{index}].meaning", 40)
    if meaning and meaning not in MEANINGS:
        meaning = ""  # a meaning this Sida does not know is no meaning; nothing is guessed
    color = _text(raw.get("color"), f"layers[{index}].color", 7)
    if color and not COLOR.fullmatch(color):
        raise ValueError(f"layers[{index}].color must be #rrggbb")
    height = raw.get("floor_height")
    return {
        "path": path, "meaning": meaning, "color": color.lower(),
        "floor_height": None if height is None else _number(height, f"layers[{index}].floor_height", low=0.1, high=20),
    }


def _mesh(raw, what: str) -> dict | None:
    """A small mesh for the screen, or None when it is too big or malformed (the figures do not need it)."""
    if not isinstance(raw, dict):
        return None
    try:
        vertices = _points(raw.get("v"), f"{what}.v", 3, MAX_MESH_VERTICES)
        faces = raw.get("f")
        if not isinstance(faces, list) or len(faces) > 2 * MAX_MESH_VERTICES:
            return None
        clean = []
        for face in faces:
            if not isinstance(face, (list, tuple)) or len(face) not in (3, 4):
                return None
            if any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(vertices) for i in face):
                return None
            clean.append([int(i) for i in face])
    except ValueError:
        return None
    return {"v": vertices, "f": clean} if vertices and clean else None


def _object(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"objects[{index}] must be an object")
    what = f"objects[{index}]"
    oid = _text(raw.get("id"), f"{what}.id", 64)
    if not oid:
        raise ValueError(f"{what} needs an id")
    item: dict = {
        "id": oid,
        "sida_id": _text(raw.get("sida_id"), f"{what}.sida_id", 80) or None,
        "layer": _text(raw.get("layer"), f"{what}.layer"),
        "name": _text(raw.get("name"), f"{what}.name", 120),
        "volume": None if raw.get("volume") is None else round(_number(raw["volume"], f"{what}.volume", low=0), 3),
        "height": None if raw.get("height") is None else round(_number(raw["height"], f"{what}.height", low=0), 3),
        "base": None if raw.get("base") is None else round(_number(raw["base"], f"{what}.base"), 3),
        "footprint": None,
        "floors": [],
    }
    if raw.get("footprint") is not None:
        item["footprint"] = _rings(raw["footprint"], f"{what}.footprint")
    floors = raw.get("floors") or []
    if not isinstance(floors, list) or len(floors) > MAX_FLOORS:
        raise ValueError(f"{what}.floors must be a list of at most {MAX_FLOORS} floors")
    for i, floor in enumerate(floors):
        if not isinstance(floor, dict):
            raise ValueError(f"{what}.floors[{i}] must be an object")
        item["floors"].append({
            "z": round(_number(floor.get("z"), f"{what}.floors[{i}].z"), 3),
            "area": round(_number(floor.get("area"), f"{what}.floors[{i}].area", low=0), 3),
        })
    if raw.get("mesh") is not None:
        mesh = _mesh(raw["mesh"], f"{what}.mesh")
        if mesh is None:
            item["mesh_dropped"] = True
        else:
            item["mesh"] = mesh
    note = _text(raw.get("note"), f"{what}.note", 400)
    if note:
        item["note"] = note
    return item


def clean_snapshot(raw) -> dict:
    """The snapshot with only what Sida reads, checked. Raises ValueError with a plain reason."""
    if not isinstance(raw, dict):
        raise ValueError("the snapshot must be a JSON object")
    if raw.get("schema") != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    rhino = raw.get("rhino") if isinstance(raw.get("rhino"), dict) else {}
    units = _text(rhino.get("units"), "rhino.units", 10).lower()
    if units != "m":
        raise ValueError("rhino.units must be m (the plugin converts before sending)")
    out: dict = {
        "schema": SCHEMA,
        "rhino": {
            "version": _text(rhino.get("version"), "rhino.version", 40),
            "file": _text(rhino.get("file"), "rhino.file"),
            "units": "m",
        },
    }
    origin = raw.get("origin")
    if isinstance(origin, dict) and origin.get("lon") is not None and origin.get("lat") is not None:
        out["origin"] = {
            "lon": round(_number(origin["lon"], "origin.lon", low=-180, high=180), 7),
            "lat": round(_number(origin["lat"], "origin.lat", low=-90, high=90), 7),
            "matches_project": origin.get("matches_project") is True,
        }
    layers = raw.get("layers") or []
    if not isinstance(layers, list) or len(layers) > MAX_LAYERS:
        raise ValueError(f"layers must be a list of at most {MAX_LAYERS} layers")
    out["layers"] = [_layer(x, i) for i, x in enumerate(layers)]
    objects = raw.get("objects") or []
    if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
        raise ValueError(f"objects must be a list of at most {MAX_OBJECTS} objects")
    out["objects"] = [_object(x, i) for i, x in enumerate(objects)]
    if len({o["id"] for o in out["objects"]}) != len(out["objects"]):
        raise ValueError("every object needs its own id")
    views = raw.get("views") or []
    if not isinstance(views, list) or len(views) > MAX_VIEWS:
        raise ValueError(f"views must be a list of at most {MAX_VIEWS} views")
    out["views"] = []
    for i, view in enumerate(views):
        if not isinstance(view, dict):
            raise ValueError(f"views[{i}] must be an object")
        kind = _text(view.get("kind"), f"views[{i}].kind", 20)
        file = _text(view.get("file"), f"views[{i}].file", 50)
        if kind not in VIEW_KINDS:
            raise ValueError(f"views[{i}].kind must be one of {', '.join(VIEW_KINDS)}")
        if not VIEW_FILE.fullmatch(file) or any(v["file"] == file for v in out["views"]):
            raise ValueError(f"views[{i}].file must be a unique name like plan.png")
        out["views"].append({"kind": kind, "file": file})
    return out


# ---------------------------------------------------------------------------
# Figures: what Sida computes from what Rhino measured
# ---------------------------------------------------------------------------


def meaning_of(snapshot: dict) -> dict[str, str]:
    """Layer path → meaning code ('' for a layer without one)."""
    return {layer["path"]: layer["meaning"] for layer in snapshot["layers"]}


def _shape(rings: list[list[list[float]]]):
    """One footprint as a shape, by the even-odd rule: a ring inside another is a hole."""
    from shapely.geometry import Polygon

    shape = None
    for ring in rings:
        part = Polygon(ring)
        if not part.is_valid:
            part = part.buffer(0)
        if not part.is_empty:
            shape = part if shape is None else shape.symmetric_difference(part)
    return shape


def _union_area(footprints: list[list[list[list[float]]]]) -> float:
    """The ground the footprints cover together (overlaps counted once, courtyards left out)."""
    from shapely.ops import unary_union

    shapes = [shape for shape in map(_shape, footprints) if shape is not None and not shape.is_empty]
    return float(unary_union(shapes).area) if shapes else 0.0


def counted_floors(item: dict, floor_height: float | None) -> list[dict]:
    """
    The floors of an object that count as floors. The plugin cuts the body at every floor
    height from its base, so a mass a little taller than its storeys (a parapet, a roof slab)
    gets one cut too many: a level counts only when the body fills at least half a storey above
    it. Without the layer's floor height or the object's base and height, all cuts count.
    """
    if not floor_height or item["base"] is None or item["height"] is None:
        return item["floors"]
    top = item["base"] + item["height"]
    return [floor for floor in item["floors"] if floor["z"] + floor_height / 2 <= top + 0.001]


def figures(snapshot: dict, site_area: float | None) -> dict:
    """
    Floor area, footprint, volume and height of the objects whose layers mean building, by
    meaning and in all; coverage and FAR only with a known site area. Objects Rhino could not
    measure are listed as unmeasured, and those on a layer without a floor height as such
    (they have a footprint but no floor area); nothing is estimated.
    """
    meaning = meaning_of(snapshot)
    floor_heights = {layer["path"]: layer["floor_height"] for layer in snapshot["layers"]}
    by: dict[str, dict] = {}
    outlines: list = []
    unmeasured: list[str] = []
    no_floor_height: list[str] = []
    unassigned = 0
    volume = 0.0
    volume_known = True
    tallest = None
    spans: list[tuple[float, float]] | None = []  # (base, top) of every built object; None once one has no base
    for item in snapshot["objects"]:
        code = meaning.get(item["layer"], "")
        if not code:
            unassigned += 1
            continue
        if code not in BUILT:
            continue
        part = by.setdefault(code, {"meaning": code, "word": MEANINGS[code]["word"], "floor_area_m2": 0.0,
                                     "footprint_m2": 0.0, "objects": 0})
        part["objects"] += 1
        floor_height = floor_heights.get(item["layer"])
        part["floor_area_m2"] += sum(f["area"] for f in counted_floors(item, floor_height))
        if item["footprint"]:
            part["footprint_m2"] += _union_area([item["footprint"]])
            outlines.append(item["footprint"])
        if item["volume"] is None:
            volume_known = False
        else:
            volume += item["volume"]
        if item["footprint"] and not item["floors"] and not floor_height:
            no_floor_height.append(item["id"])
        elif item["volume"] is None or not item["floors"] or not item["footprint"]:
            unmeasured.append(item["id"])
        if item["height"] is not None:
            tallest = item["height"] if tallest is None else max(tallest, item["height"])
            if item["base"] is None:
                spans = None
            elif spans is not None:
                spans.append((item["base"], item["base"] + item["height"]))
    # With every base known the height is the highest top above the lowest base (a tower on a
    # podium is one height); otherwise only the tallest single object can be said.
    height = max(top for _base, top in spans) - min(base for base, _top in spans) if spans else tallest
    floor_area = sum(p["floor_area_m2"] for p in by.values())
    footprint = _union_area(outlines)
    out = {
        "floor_area_m2": round(floor_area, 1),
        "footprint_m2": round(footprint, 1),
        "volume_m3": round(volume, 1) if by and volume_known else None,
        "height_m": None if height is None else round(height, 1),
        "coverage_pct": round(footprint / site_area * 100, 1) if site_area else None,
        "far_pct": round(floor_area / site_area * 100, 1) if site_area else None,
        "site_area_m2": site_area,
        "objects": sum(p["objects"] for p in by.values()),
        "unmeasured": unmeasured,
        "no_floor_height": no_floor_height,
        "unassigned": unassigned,
        "by_meaning": [
            {**p, "floor_area_m2": round(p["floor_area_m2"], 1), "footprint_m2": round(p["footprint_m2"], 1)}
            for p in by.values()
        ],
    }
    return out


def limits(project_path: Path) -> list[dict]:
    """
    The coverage and FAR limits of the site's zones, from the site facts as they stand: the
    statutory ones and, when the ordinance article was read by rule, the ordinance's. [] without
    a site. Nothing here is computed; it is what the site domain already holds.
    """
    from sida.experts.site import site_facts

    facts = site_facts.load_facts(project_path)
    if not facts:
        return []
    values = (facts.get("ordinance") or {}).get("values") or {}
    out = []
    for zone in facts["summary"].get("zoning") or []:
        read = values.get(zone["zone"]) or {}
        out.append({
            "zone": zone["zone"],
            "bcr_max": zone.get("bcr_max"),
            "far_min": zone.get("far_min"),
            "far_max": zone.get("far_max"),
            "ordinance_bcr": (read.get("bcr") or {}).get("value"),
            "ordinance_far": (read.get("far") or {}).get("value"),
        })
    return out


def _pct(value: float | None) -> str:
    return "미확인" if value is None else f"{value:,.1f}%"


def figure_lines(fig: dict) -> list[str]:
    """The figures as the paper and the experts read them (Korean, like the table's figures)."""
    lines = [
        f"연면적 {fig['floor_area_m2']:,.1f}㎡"
        + (" (" + ", ".join(f"{p['word']} {p['floor_area_m2']:,.1f}" for p in fig["by_meaning"]) + ")" if len(fig["by_meaning"]) > 1 else ""),
        f"건축면적 {fig['footprint_m2']:,.1f}㎡",
        f"건폐율 {_pct(fig['coverage_pct'])} · 용적률 {_pct(fig['far_pct'])}"
        + ("" if fig["site_area_m2"] else " (대지 면적 미확인)"),
    ]
    if fig["height_m"] is not None:
        lines.append(f"최고 높이 {fig['height_m']:,.1f}m")
    if fig["volume_m3"] is not None:
        lines.append(f"부피 {fig['volume_m3']:,.1f}㎥")
    if fig["unmeasured"]:
        lines.append(f"잴 수 없는 개체 {len(fig['unmeasured'])}개 (닫히지 않은 도형)")
    if fig.get("no_floor_height"):
        lines.append(f"층고를 정하지 않은 레이어의 개체 {len(fig['no_floor_height'])}개 (연면적에서 제외)")
    if fig["unassigned"]:
        lines.append(f"의미 없는 레이어의 개체 {fig['unassigned']}개 (수치에서 제외)")
    return lines


# ---------------------------------------------------------------------------
# Saving under the project
# ---------------------------------------------------------------------------


def snapshots_dir(project_path: Path) -> Path:
    return Path(project_path) / SNAPSHOT_DIR


def _summary(snapshot: dict) -> dict:
    return {
        "id": snapshot["id"],
        "taken_at": snapshot["taken_at"],
        "file": snapshot["rhino"]["file"],
        "version": snapshot["rhino"]["version"],
        "objects": len(snapshot["objects"]),
        "layers": [{"path": x["path"], "meaning": x["meaning"]} for x in snapshot["layers"]],
        "views": snapshot["views"],
        "origin": snapshot.get("origin"),
    }


def save_snapshot(project_path: Path, raw, views: dict[str, bytes]) -> dict:
    """
    Check the snapshot and keep it with its view images (file name → PNG bytes; every declared
    view needs its file). Returns the saved snapshot (with `id` and `taken_at`). The oldest
    snapshots over MAX_SNAPSHOTS are removed. Raises ValueError.
    """
    snapshot = clean_snapshot(raw)
    for view in snapshot["views"]:
        data = views.get(view["file"])
        if data is None:
            raise ValueError(f"the view file {view['file']} was not sent")
        if not data.startswith(PNG) or len(data) > MAX_VIEW_BYTES:
            raise ValueError(f"the view file {view['file']} must be a PNG under {MAX_VIEW_BYTES // (1024 * 1024)} MB")
    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    same_second = sum(1 for p in _folders(project_path) if p.name.startswith(stamp))
    snapshot_id = f"{stamp}-{same_second + 1:04d}"  # ids sort in the order the snapshots came
    saved = {"id": snapshot_id, "taken_at": now.isoformat(timespec="seconds"), **snapshot}
    folder = snapshots_dir(project_path) / snapshot_id
    (folder / "views").mkdir(parents=True, exist_ok=True)
    for view in snapshot["views"]:
        (folder / "views" / view["file"]).write_bytes(views[view["file"]])
    atomic_write_text(folder / "snapshot.json", json.dumps(saved, ensure_ascii=False) + "\n")
    for old in _folders(project_path)[MAX_SNAPSHOTS:]:
        shutil.rmtree(old, ignore_errors=True)
    return saved


def _folders(project_path: Path) -> list[Path]:
    """Snapshot folders, newest first."""
    root = snapshots_dir(project_path)
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and SNAPSHOT_ID.fullmatch(p.name)), key=lambda p: p.name, reverse=True)


class SnapshotNotFound(LookupError):
    pass


def load_snapshot(project_path: Path, snapshot_id: str) -> dict:
    """A saved snapshot whole. Raises SnapshotNotFound."""
    if not SNAPSHOT_ID.fullmatch(str(snapshot_id or "")):
        raise SnapshotNotFound(snapshot_id)
    path = snapshots_dir(project_path) / snapshot_id / "snapshot.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SnapshotNotFound(snapshot_id) from None


def latest_snapshot(project_path: Path) -> dict | None:
    for folder in _folders(project_path):
        try:
            return load_snapshot(project_path, folder.name)
        except SnapshotNotFound:
            continue
    return None


def list_snapshots(project_path: Path) -> list[dict]:
    """Summaries of the saved snapshots, newest first."""
    out = []
    for folder in _folders(project_path):
        try:
            out.append(_summary(load_snapshot(project_path, folder.name)))
        except SnapshotNotFound:
            continue
    return out


def view_file(project_path: Path, snapshot_id: str, file: str) -> Path:
    """The PNG of one view of a snapshot. Raises SnapshotNotFound (for the snapshot or the view)."""
    snapshot = load_snapshot(project_path, snapshot_id)
    if not any(v["file"] == file for v in snapshot["views"]):
        raise SnapshotNotFound(file)
    path = snapshots_dir(project_path) / snapshot_id / "views" / file
    if not path.is_file():
        raise SnapshotNotFound(file)
    return path


def delete_snapshot(project_path: Path, snapshot_id: str) -> None:
    load_snapshot(project_path, snapshot_id)
    shutil.rmtree(snapshots_dir(project_path) / snapshot_id, ignore_errors=True)


def summary(snapshot: dict) -> dict:
    return _summary(snapshot)


# ---------------------------------------------------------------------------
# For the experts
# ---------------------------------------------------------------------------

HEADER = "## Rhino model (the designer's own work)"


def prompt_text(snapshot: dict, fig: dict) -> str:
    """The newest snapshot for an expert's prompt: figures Sida computed from what Rhino measured,
    the layers' meanings, never the geometry."""
    layers = [f"{x['path']} = {MEANINGS[x['meaning']]['word']}" for x in snapshot["layers"] if x["meaning"]]
    lines = [
        HEADER,
        f"Snapshot {snapshot['taken_at']} from {snapshot['rhino']['file'] or 'an unsaved Rhino document'} "
        f"({len(snapshot['objects'])} objects). Figures computed by Sida from the geometry Rhino measured; "
        "ratios are against the site area in the site facts. Unmeasured objects are not estimated.",
        *(f"- {line}" for line in figure_lines(fig)),
    ]
    if layers:
        lines.append("- Layer meanings (the designer's): " + "; ".join(layers))
    return "\n".join(lines)
