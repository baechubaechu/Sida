"""The drawing table as a CAD (DXF) or Rhino (3dm) file, so a scheme can go on in those programs.

Independent of HTTP and of the screen. `export_scene` turns the saved table into plain
geometry in metres around the site's middle (x east, y north, z up), the frame the screen
draws in (board.site_plan): the site's parcel boundaries, every massing scheme on the table
as closed boxes, and the pen lines of each tracing sheet. Each kind of thing is its own layer
group and each paper its own layer, so the designer can turn schemes on and off. Papers in
the AI section are left out: only what the designer laid on the table goes out.

`to_dxf` and `to_3dm` write that scene. DXF (AutoCAD 2013) keeps masses as MESH entities and
lines as polylines; 3dm keeps masses as closed extrusions, lines as polyline curves and the
labels as text dots. Both are in metres.

Another domain can add layers (for example buildings around the site) with a hook
`board_export_layers(project_dir) -> list[layer]` in its hooks.py, in the same layer form.
A layer may also hold `surfaces`: height grids (the ground around a site), written as a NURBS
surface through the grid in 3dm and as a MESH in DXF.
"""

from __future__ import annotations

import io
import math
import os
import re
import tempfile
from pathlib import Path

from sida import board

FORMATS = ("dxf", "3dm")
MEDIA_TYPES = {"dxf": "application/dxf", "3dm": "application/octet-stream"}

# Layer groups as the designer reads them in CAD and Rhino (Korean, like the screen).
SITE_LAYER = "대지 경계"
MASS_GROUP = "매스"
TRACING_GROUP = "트레이싱"
ORIGIN_LAYER = "기준점"
COLORS = {
    "site": (200, 40, 40),
    "mass": (70, 70, 70),
    "tracing": (30, 90, 200),
    "origin": (120, 120, 120),
}
TEXT_FONT = "malgun.ttf"  # a Windows font with Hangul, so AutoCAD shows Korean labels
_BAD_NAME = re.compile(r'[<>/\\":;?*|=,`{}\[\]]+|::')


# ---------------------------------------------------------------------------
# The scene: what goes in the file, as plain data
# ---------------------------------------------------------------------------


def layer(name: str, color, *, parent: str = "", visible: bool = True) -> dict:
    """An empty layer: curves [{points [[x,y,z]], closed}], solids [{outline [[x,y]] counter-
    clockwise, base, height}], surfaces [{min_x, min_y, step, nx, ny, z}] (heights row by row
    from the south-west corner) and labels [{at [x,y,z], text}]. Optional: `short` (its name
    under the parent group in Rhino) and `linetype` (a DXF linetype such as DASHED)."""
    return {
        "name": name, "parent": parent, "color": tuple(color), "visible": visible,
        "curves": [], "solids": [], "surfaces": [], "labels": [],
    }


def layer_name(text: str, fallback: str) -> str:
    """A name both AutoCAD and Rhino accept (no <>/\\":;?*|=,` and no '::')."""
    name = " ".join(_BAD_NAME.sub(" ", str(text or "")).split())[:60].strip()
    return name or fallback


def _unique(name: str, taken: set[str]) -> str:
    out, n = name, 2
    while out in taken:
        out, n = f"{name} {n}", n + 1
    taken.add(out)
    return out


def block_outline(frame: dict | None, block: dict) -> list[list[float]]:
    """A block's footprint corners on the table, counter-clockwise (board-model.js blockCorners)."""
    f = frame or {"x": 0.0, "y": 0.0, "angle": 0.0}
    c, s = math.cos(f["angle"]), math.sin(f["angle"])
    a = math.radians(block.get("a") or 0)
    ca, sa = math.cos(a), math.sin(a)
    corners = []
    for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        lu, lv = su * block["w"] / 2, sv * block["d"] / 2
        u = block["u"] + lu * ca - lv * sa
        v = block["v"] + lu * sa + lv * ca
        corners.append([round(f["x"] + u * c - v * s, 4), round(f["y"] + u * s + v * c, 4)])
    return corners


def _ccw(outline: list[list[float]]) -> list[list[float]]:
    area = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(outline, outline[1:] + outline[:1], strict=True)
    )
    return outline if area >= 0 else outline[::-1]


def export_scene(project_path: Path, *, active: str | None = None, hooks=None) -> dict:
    """
    The table as layers of geometry. `active` names the scheme shown on the screen: its layer
    is on and the other schemes' layers are off (all on when it is not given).
    Raises ValueError when `active` is not a scheme on the table.
    """
    from sida.experts import domain_hooks

    hooks = domain_hooks() if hooks is None else hooks
    saved = board.load_board(project_path)
    summary = board.site_summary(project_path, hooks)
    plan = board.site_plan((summary or {}).get("parcels") or [])
    frame = (plan or {}).get("frame")
    masses = [p for p in saved["papers"] if p.get("kind") == "mass"]
    if active and not any(p["id"] == active for p in masses):
        raise ValueError(f"not a massing scheme on the table: {active}")

    layers: list[dict] = []
    taken: set[str] = set()

    site = layer(_unique(SITE_LAYER, taken), COLORS["site"])
    site["linetype"] = "DASHED"  # drawn dashed on the screen too
    for parcel in (plan or {}).get("parcels") or []:
        for ring in parcel["rings"]:
            site["curves"].append({"points": [[x, y, 0.0] for x, y in ring], "closed": True})
        label = parcel.get("address") or parcel.get("pnu")
        if label and parcel["rings"]:
            x, y = board._centroid(parcel["rings"][0])
            site["labels"].append({"at": [round(x, 3), round(y, 3), 0.0], "text": str(label)})
    if site["curves"]:
        layers.append(site)

    for paper in masses:
        name = _unique(f"{MASS_GROUP} - {layer_name(board.paper_name(paper), paper['id'])}", taken)
        mass = layer(name, COLORS["mass"], parent=MASS_GROUP, visible=not active or paper["id"] == active)
        mass["short"] = name.removeprefix(f"{MASS_GROUP} - ")
        storey = float(paper.get("floor_height") or board.DEFAULT_FLOOR_HEIGHT)
        for block in paper.get("blocks") or []:
            outline = block_outline(frame, block)
            height = round(block["floors"] * storey, 4)
            mass["solids"].append({"outline": _ccw(outline), "base": 0.0, "height": height})
            cx = sum(x for x, _ in outline) / 4
            cy = sum(y for _, y in outline) / 4
            mass["labels"].append({"at": [round(cx, 3), round(cy, 3), height], "text": f"{block['floors']}F"})
        layers.append(mass)

    for paper in saved["papers"]:
        if paper.get("kind") != "tracing" or not paper.get("strokes"):
            continue
        name = _unique(f"{TRACING_GROUP} - {layer_name(board.paper_name(paper), paper['id'])}", taken)
        sheet = layer(name, COLORS["tracing"], parent=TRACING_GROUP)
        sheet["short"] = name.removeprefix(f"{TRACING_GROUP} - ")
        for stroke in paper["strokes"]:
            if len(stroke) >= 2:
                sheet["curves"].append({"points": [[x, y, 0.0] for x, y in stroke], "closed": False})
        layers.append(sheet)

    for _domain, module in hooks:
        provide = getattr(module, "board_export_layers", None)
        if provide is None:
            continue
        for extra in provide(Path(project_path)) or []:
            extra = {**layer(extra.get("name") or "", extra.get("color") or (128, 128, 128)), **extra}
            extra["name"] = _unique(layer_name(extra["name"], _domain), taken)
            layers.append(extra)

    origin = None
    if plan and plan.get("origin"):
        origin = plan["origin"]
        mark = layer(_unique(ORIGIN_LAYER, taken), COLORS["origin"])
        mark["labels"].append({"at": [0.0, 0.0, 0.0], "text": origin_text(origin)})
        layers.append(mark)
    return {"origin": origin, "layers": layers}


def origin_text(origin: dict) -> str:
    """Where 0, 0 lies on the earth, for the label at the origin and the file's notes."""
    lat, lon = origin["lat"], origin["lon"]
    return (
        f"원점 {abs(lat):.6f}°{'N' if lat >= 0 else 'S'} {abs(lon):.6f}°{'E' if lon >= 0 else 'W'}"
        " · 단위 m · 위쪽(+Y)이 북쪽"
    )


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _prism_mesh(solid: dict) -> tuple[list[tuple], list[tuple]]:
    """Vertices and faces of a closed prism, faces facing out."""
    outline = solid["outline"]
    n = len(outline)
    base, top = solid["base"], solid["base"] + solid["height"]
    vertices = [(x, y, base) for x, y in outline] + [(x, y, top) for x, y in outline]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return vertices, faces


def _grid_points(surface: dict) -> list[list[tuple]]:
    """The grid's points, [row][column] from the south-west corner."""
    nx, ny, step = surface["nx"], surface["ny"], surface["step"]
    z = surface["z"]
    return [
        [(surface["min_x"] + i * step, surface["min_y"] + j * step, float(z[j * nx + i])) for i in range(nx)]
        for j in range(ny)
    ]


def to_dxf(scene: dict) -> bytes:
    """The scene as an AutoCAD 2013 DXF in metres (UTF-8)."""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    doc = ezdxf.new("R2013", setup=True, units=6)  # 6 = metres
    doc.header["$MEASUREMENT"] = 1
    style = doc.styles.new("SIDA", dxfattribs={"font": TEXT_FONT})
    if scene.get("origin"):
        doc.header.custom_vars.append("Sida origin", origin_text(scene["origin"]))
    msp = doc.modelspace()
    for item in scene["layers"]:
        name = item["name"]
        entry = doc.layers.add(name, true_color=ezdxf.colors.rgb2int(item["color"]))
        if item.get("linetype"):
            entry.dxf.linetype = item["linetype"]
        if not item["visible"]:
            entry.off()
        attribs = {"layer": name}
        for curve in item["curves"]:
            points = curve["points"]
            if all(abs(z) < 1e-9 for _x, _y, z in points):  # flat: a 2D polyline AutoCAD can offset
                msp.add_lwpolyline([(x, y) for x, y, _z in points], close=curve["closed"], dxfattribs=attribs)
            else:
                msp.add_polyline3d(points, close=curve["closed"], dxfattribs=attribs)
        for solid in item["solids"]:
            vertices, faces = _prism_mesh(solid)
            mesh = msp.add_mesh(dxfattribs=attribs)
            with mesh.edit_data() as data:
                data.vertices = vertices
                data.faces = faces
        for surface in item.get("surfaces") or []:
            rows = _grid_points(surface)
            nx = surface["nx"]
            mesh = msp.add_mesh(dxfattribs=attribs)
            with mesh.edit_data() as data:
                data.vertices = [p for row in rows for p in row]
                data.faces = [
                    (j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i)
                    for j in range(len(rows) - 1) for i in range(nx - 1)
                ]
        for label in item["labels"]:
            msp.add_text(
                label["text"], height=1.2, dxfattribs={**attribs, "style": style.dxf.name}
            ).set_placement(tuple(label["at"]), align=TextEntityAlignment.MIDDLE_CENTER)
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def to_3dm(scene: dict) -> bytes:
    """The scene as a Rhino 3dm (Rhino 7 and later open it) in metres."""
    import rhino3dm as r

    model = r.File3dm()
    model.Settings.ModelUnitSystem = r.UnitSystem.Meters
    model.Settings.ModelAbsoluteTolerance = 0.001
    parents: dict[str, int] = {}

    def add_layer(name: str, color, visible: bool, parent: int | None) -> int:
        item = r.Layer()
        item.Name = name
        item.Color = (*color, 255)
        item.Visible = visible
        if parent is not None:
            item.ParentLayerId = model.Layers[parent].Id
        return model.Layers.Add(item)

    for scene_layer in scene["layers"]:
        parent = None
        if scene_layer.get("parent"):
            group = scene_layer["parent"]
            if group not in parents:
                parents[group] = add_layer(group, scene_layer["color"], True, None)
            parent = parents[group]
        name = scene_layer["name"]
        if parent is not None:  # a sublayer shows only its own part under the group
            name = scene_layer.get("short") or name
        index = add_layer(name, scene_layer["color"], scene_layer["visible"], parent)
        attributes = r.ObjectAttributes()
        attributes.LayerIndex = index
        for curve in scene_layer["curves"]:
            points = [r.Point3d(*p) for p in curve["points"]]
            if curve["closed"]:
                points.append(points[0])
            model.Objects.AddPolyline(points, attributes)
        for solid in scene_layer["solids"]:
            outline = [r.Point3d(x, y, 0.0) for x, y in solid["outline"]]
            outline.append(outline[0])
            body = r.Extrusion.Create(r.PolylineCurve(outline), solid["height"], True)
            if body is None:
                continue
            if solid["base"]:
                body.Translate(r.Vector3d(0, 0, solid["base"]))
            model.Objects.AddExtrusion(body, attributes)
        for surface in scene_layer.get("surfaces") or []:
            body = _nurbs(r, surface)
            if body is not None:
                model.Objects.AddSurface(body, attributes)
        for label in scene_layer["labels"]:
            model.Objects.AddTextDot(label["text"], r.Point3d(*label["at"]), attributes)
    handle, path = tempfile.mkstemp(suffix=".3dm")
    os.close(handle)
    try:
        if not model.Write(path, 7):
            raise RuntimeError("rhino3dm could not write the 3dm file")
        return Path(path).read_bytes()
    finally:
        os.unlink(path)


def _nurbs(r, surface: dict):
    """A NURBS surface with the grid as its control points (cubic where the grid allows it):
    smooth, through the four corners, within a fraction of a metre of the grid elsewhere."""
    rows = _grid_points(surface)
    nu, nv = surface["nx"], surface["ny"]
    if nu < 2 or nv < 2:
        return None
    order_u, order_v = min(4, nu), min(4, nv)
    body = r.NurbsSurface.Create(3, False, order_u, order_v, nu, nv)
    body.KnotsU.CreateUniformKnots(1.0)
    body.KnotsV.CreateUniformKnots(1.0)
    for j, row in enumerate(rows):
        for i, (x, y, z) in enumerate(row):
            body.Points[(i, j)] = r.Point4d(x, y, z, 1.0)
    return body if body.IsValid else None


WRITERS = {"dxf": to_dxf, "3dm": to_3dm}


def export_board(project_path: Path, fmt: str, *, active: str | None = None, hooks=None) -> bytes:
    """The table as a file in `fmt` (dxf or 3dm). Raises ValueError."""
    fmt = str(fmt or "").lower()
    if fmt not in WRITERS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}")
    scene = export_scene(project_path, active=active, hooks=hooks)
    try:
        return WRITERS[fmt](scene)
    except ImportError as exc:  # installed before the dependency was added
        raise ValueError(
            f"the {exc.name or 'export'} package is not installed; run `run.bat update` "
            "(or pip install -e .) and start Sida again"
        ) from exc
