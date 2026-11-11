"""The drawing table as a CAD (DXF) or Rhino (3dm) file, so a scheme can go on in those programs.

Independent of HTTP and of the screen. `export_scene` turns the saved table into plain
geometry in metres around the site's middle (x east, y north, z up), the frame the screen
draws in (board.site_plan): the site's parcel boundaries, every massing scheme on the table
as closed boxes, and the pen lines of each tracing sheet. Each kind of thing is its own layer
group and each paper its own layer, so the designer can turn schemes on and off. Papers in
the AI section are left out: only what the designer laid on the table goes out. A block or a
tracing sheet the designer put on a layer of their own (board `layers`, 2026-11-09) goes out on a
layer of that name instead ("매스 - 타워" for a sublayer, in the layer's colour when it has one).

Each thing that came from a paper carries the paper's `id` (a block of a mass as `<paper id>:<block
index>`, a parcel as `site:<pnu>`, the origin mark as `origin`) and its `kind`; `to_3dm` writes them
on the object as user strings `sida.id` and `sida.kind` (and `sida.project`, `sida.origin` on the
origin mark), so the Rhino plugin can tell Sida's objects from the designer's and send a changed
block back with its id (sida/experts/rhino/snapshot.py). DXF carries no ids.

`to_dxf` and `to_3dm` write that scene. DXF (AutoCAD 2013) keeps masses as MESH entities and
lines as polylines; 3dm keeps masses as closed extrusions, lines as polyline curves and the
labels as text dots. Both are in metres.

Another domain can add layers (for example buildings around the site) with a hook
`board_export_layers(project_dir) -> list[layer]` in its hooks.py, in the same layer form.
A layer may also hold `surfaces`: height grids (the ground around a site), written as a NURBS
surface through the grid in 3dm and as a MESH in DXF. A grid with `clip_radius` (a round range)
is written as a mesh of only the cells within that distance of the origin, in both.

A domain that knows the ground around the site gives it with `board_ground(project_dir) ->
surface | None` (the surface form above). Each block of a mass then stands on the lowest ground
under its footprint (`mass_base`, the same rule as the screen's board-model.js massBase), so no
building floats on a slope; without it masses stand at z = 0. The saved table is not changed.
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
    clockwise, base, height}], surfaces [{min_x, min_y, step, nx, ny, z, clip_radius?}] (heights row by row
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


def _designer_layers(saved: list[dict], taken: set[str]) -> dict[str, dict]:
    """
    The designer's own layers (not the ones a table starts with, one per kind) as empty export
    layers by id, named by their path ("매스 - 타워"), in their colour or the masses' grey.
    """
    kinds = {layer_id for layer_id, _name in board.DEFAULT_LAYERS}
    by_id = {x["id"]: x for x in saved if isinstance(x, dict) and x.get("id")}
    out: dict[str, dict] = {}
    for layer_id, item in by_id.items():
        if layer_id in kinds:
            continue
        path, at, seen = [], item, set()
        while at and at["id"] not in seen:
            seen.add(at["id"])
            path.insert(0, layer_name(at.get("name") or "", at["id"]))
            at = by_id.get(at.get("parent") or "")
        color = item.get("color") or ""
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) if len(color) == 7 else COLORS["mass"]
        made = layer(_unique(" - ".join(path), taken), rgb)
        made["short"] = path[-1]
        out[layer_id] = made
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


def ground_at(ground: dict, x: float, y: float) -> float | None:
    """The height of a surface grid at (x, y), bilinear; None outside the grid."""
    nx, ny, step = ground["nx"], ground["ny"], ground["step"]
    fx, fy = (x - ground["min_x"]) / step, (y - ground["min_y"]) / step
    if not (0 <= fx <= nx - 1 and 0 <= fy <= ny - 1):
        return None
    i, j = min(int(fx), nx - 2), min(int(fy), ny - 2)
    tx, ty = fx - i, fy - j
    z = ground["z"]
    return (z[j * nx + i] * (1 - tx) * (1 - ty) + z[j * nx + i + 1] * tx * (1 - ty)
            + z[(j + 1) * nx + i] * (1 - tx) * ty + z[(j + 1) * nx + i + 1] * tx * ty)


def _inside(x: float, y: float, ring: list[list[float]]) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def lowest_ground(ground: dict | None, outline: list[list[float]]) -> float | None:
    """The lowest ground under a footprint: along its edges (every half grid step) and at the grid
    points inside it. None without a ground or when the footprint is off the grid."""
    if not ground or not outline:
        return None
    gap = ground["step"] / 2
    points = []
    for (x1, y1), (x2, y2) in zip(outline, outline[1:] + outline[:1], strict=True):
        k = max(1, math.ceil(math.hypot(x2 - x1, y2 - y1) / gap))
        points += [(x1 + (x2 - x1) * s / k, y1 + (y2 - y1) * s / k) for s in range(k)]
    xs, ys = [x for x, _ in outline], [y for _, y in outline]
    step = ground["step"]
    for i in range(max(0, math.ceil((min(xs) - ground["min_x"]) / step)), min(ground["nx"], math.floor((max(xs) - ground["min_x"]) / step) + 1)):
        for j in range(max(0, math.ceil((min(ys) - ground["min_y"]) / step)), min(ground["ny"], math.floor((max(ys) - ground["min_y"]) / step) + 1)):
            x, y = ground["min_x"] + i * step, ground["min_y"] + j * step
            if _inside(x, y, outline):
                points.append((x, y))
    heights = [h for h in (ground_at(ground, x, y) for x, y in points) if h is not None]
    return round(min(heights), 2) if heights else None


def mass_base(outline: list[list[float]], ground: dict | None, datum: float | None = None) -> float:
    """
    Where a block of a mass stands (z of its floor): `datum` when one 계획고 is given for every
    mass, else the lowest ground under its footprint (it never floats on a slope; uphill it goes
    into the ground like a basement), else the table (0). board-model.js massBase is the same.
    """
    if datum is not None:
        return float(datum)
    low = lowest_ground(ground, outline)
    return 0.0 if low is None else low


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
    ground = None
    for _domain, module in hooks:
        give = getattr(module, "board_ground", None)
        if give is not None and ground is None:
            ground = give(Path(project_path))
    if active and not any(p["id"] == active for p in masses):
        raise ValueError(f"not a massing scheme on the table: {active}")

    layers: list[dict] = []
    taken: set[str] = set()
    own = _designer_layers(saved.get("layers") or [], taken)

    site = layer(_unique(SITE_LAYER, taken), COLORS["site"])
    site["linetype"] = "DASHED"  # drawn dashed on the screen too
    for parcel in (plan or {}).get("parcels") or []:
        parcel_id = f"site:{parcel.get('pnu') or ''}"
        for ring in parcel["rings"]:
            site["curves"].append({"points": [[x, y, 0.0] for x, y in ring], "closed": True, "id": parcel_id, "kind": "site"})
        label = parcel.get("address") or parcel.get("pnu")
        if label and parcel["rings"]:
            x, y = board._centroid(parcel["rings"][0])
            site["labels"].append({"at": [round(x, 3), round(y, 3), 0.0], "text": str(label), "id": parcel_id, "kind": "site"})
    if site["curves"]:
        layers.append(site)

    for paper in masses:
        name = _unique(f"{MASS_GROUP} - {layer_name(board.paper_name(paper), paper['id'])}", taken)
        mass = layer(name, COLORS["mass"], parent=MASS_GROUP, visible=not active or paper["id"] == active)
        mass["short"] = name.removeprefix(f"{MASS_GROUP} - ")
        storey = float(paper.get("floor_height") or board.DEFAULT_FLOOR_HEIGHT)
        for index, block in enumerate(paper.get("blocks") or []):
            outline = block_outline(frame, block)
            height = round(block["floors"] * storey, 4)
            base = mass_base(outline, ground)
            into = own.get(block.get("layer")) or own.get(paper.get("layer")) or mass
            block_id = f"{paper['id']}:{index}"
            into["solids"].append({"outline": _ccw(outline), "base": base, "height": height, "id": block_id, "kind": "mass"})
            cx = sum(x for x, _ in outline) / 4
            cy = sum(y for _, y in outline) / 4
            into["labels"].append({"at": [round(cx, 3), round(cy, 3), round(base + height, 4)], "text": f"{block['floors']}F",
                                   "id": block_id, "kind": "mass"})
        if mass["solids"]:
            layers.append(mass)

    for paper in saved["papers"]:
        if paper.get("kind") != "tracing" or not paper.get("strokes"):
            continue
        name = _unique(f"{TRACING_GROUP} - {layer_name(board.paper_name(paper), paper['id'])}", taken)
        sheet = own.get(paper.get("layer")) or layer(name, COLORS["tracing"], parent=TRACING_GROUP)
        sheet.setdefault("short", name.removeprefix(f"{TRACING_GROUP} - "))
        for index, stroke in enumerate(paper["strokes"]):
            if len(stroke) >= 2:
                sheet["curves"].append({"points": [[x, y, 0.0] for x, y in stroke], "closed": False,
                                        "id": f"{paper['id']}:{index}", "kind": "tracing"})
        if sheet not in own.values():
            layers.append(sheet)
    layers.extend(x for x in own.values() if x["solids"] or x["curves"])

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
        mark["labels"].append({"at": [0.0, 0.0, 0.0], "text": origin_text(origin), "id": "origin", "kind": "origin"})
        layers.append(mark)
    return {"origin": origin, "project": Path(project_path).name, "layers": layers}


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


def grid_cells(surface: dict) -> list[tuple[int, int, int, int]]:
    """The grid's cells as quads of point indexes (row by row from the south-west, as _grid_points
    lists them); with `clip_radius`, only the cells whose four corners lie within it."""
    nx, ny, step = surface["nx"], surface["ny"], surface["step"]
    clip = surface.get("clip_radius")

    def kept(i, j):
        if clip is None:
            return True
        return all(math.hypot(surface["min_x"] + a * step, surface["min_y"] + b * step) <= clip + 1e-9
                   for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)))

    return [(j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i)
            for j in range(ny - 1) for i in range(nx - 1) if kept(i, j)]


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
            mesh = msp.add_mesh(dxfattribs=attribs)
            with mesh.edit_data() as data:
                data.vertices = [p for row in rows for p in row]
                data.faces = grid_cells(surface)
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

        def attrs(item: dict, layer_index: int = index) -> r.ObjectAttributes:
            """Attributes on the layer, with Sida's id and kind as user strings when the item has them."""
            attributes = r.ObjectAttributes()
            attributes.LayerIndex = layer_index
            if item.get("id"):
                attributes.SetUserString("sida.id", str(item["id"]))
                attributes.SetUserString("sida.kind", str(item.get("kind") or ""))
            if item.get("kind") == "origin":
                attributes.SetUserString("sida.project", str(scene.get("project") or ""))
                origin = scene.get("origin") or {}
                attributes.SetUserString("sida.origin", f"{origin.get('lon')},{origin.get('lat')}")
            return attributes

        attributes = attrs({})
        for curve in scene_layer["curves"]:
            points = [r.Point3d(*p) for p in curve["points"]]
            if curve["closed"]:
                points.append(points[0])
            model.Objects.AddPolyline(points, attrs(curve))
        for solid in scene_layer["solids"]:
            outline = [r.Point3d(x, y, 0.0) for x, y in solid["outline"]]
            outline.append(outline[0])
            body = r.Extrusion.Create(r.PolylineCurve(outline), solid["height"], True)
            if body is None:
                continue
            if solid["base"]:
                body.Translate(r.Vector3d(0, 0, solid["base"]))
            model.Objects.AddExtrusion(body, attrs(solid))
        for surface in scene_layer.get("surfaces") or []:
            if surface.get("clip_radius") is not None:  # a round ground: a mesh of the cells inside
                mesh = _mesh(r, surface)
                if mesh is not None:
                    model.Objects.AddMesh(mesh, attributes)
                continue
            body = _nurbs(r, surface)
            if body is not None:
                model.Objects.AddSurface(body, attributes)
        for label in scene_layer["labels"]:
            model.Objects.AddTextDot(label["text"], r.Point3d(*label["at"]), attrs(label))
    handle, path = tempfile.mkstemp(suffix=".3dm")
    os.close(handle)
    try:
        if not model.Write(path, 7):
            raise RuntimeError("rhino3dm could not write the 3dm file")
        return Path(path).read_bytes()
    finally:
        os.unlink(path)


def _mesh(r, surface: dict):
    """A mesh of the grid's cells within its clip radius (the points of the others left unused)."""
    cells = grid_cells(surface)
    if not cells:
        return None
    mesh = r.Mesh()
    for row in _grid_points(surface):
        for x, y, z in row:
            mesh.Vertices.Add(x, y, z)
    for a, b, c, d in cells:
        mesh.Faces.AddFace(a, b, c, d)
    mesh.Normals.ComputeNormals()
    mesh.Compact()
    return mesh


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
