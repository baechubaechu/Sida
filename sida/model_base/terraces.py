"""
The ground as a stepped 3D model: one flat slab per contour interval, as a contour model made of
stacked sheets looks.

Step k is the ground at or above its level (base + k × interval, metres above sea level). Its
top is at that level, so every step's edge is the contour line at its true height, and it is one
interval thick, standing on the step below. Step 0 is the whole area: the base plate.

`terrace_view` gives the steps on the drawing table (board.site_plan frame: metres from the
site's middle, x east, y north, z relative to the ground there), as polygons with holes for the
screen to extrude, so the designer can see the model before cutting it. The interval is the
designer's choice: any height, or one sheet of material (`pieces.contour_interval`).
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

from sida.model_base.buildings import Building, seat
from sida.model_base.pieces import _polygons, layer_regions
from sida.model_base.terrain import Terrain

MIN_STEP_M2 = 1.0  # smaller bits of a step are left out of the view


@dataclass
class Terrace:
    level_m: float  # metres above sea level of the step's top: the contour it stands for
    top: float  # the same on the table (z relative to the ground at the site's middle)
    bottom: float
    shape: Polygon | MultiPolygon  # the table's metres


def terraces(terrain: Terrain, interval_m: float) -> list[Terrace]:
    """The ground as steps `interval_m` apart, lowest first, placed on the drawing table."""
    base, regions = layer_regions(terrain, interval_m)
    ox, oy = terrain.origin
    steps = []
    for k, region in enumerate(regions):
        level = base + k * interval_m
        top = level - terrain.datum
        steps.append(Terrace(level_m=round(level, 3), top=round(top, 3), bottom=round(top - interval_m, 3),
                             shape=affinity.translate(region, ox, oy)))
    return steps


def _ring(coords, digits: int) -> list[list[float]]:
    pts = [[round(x, digits), round(y, digits)] for x, y in coords]
    return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts


def terrace_view(terrain: Terrain, interval_m: float, *, buildings: list[Building] | tuple = (),
                 tolerance: float = 0.2, digits: int = 2) -> dict:
    """
    The steps for the screen: {"interval", "base_elev", "datum", "steps": [{"level", "top",
    "bottom", "polygons": [{"outline" (counter-clockwise), "holes" (clockwise)}]}], "buildings":
    [{"outline", "holes", "bottom", "top", "sheets", "estimated"}]}. Outlines are simplified by
    `tolerance` m. A building with a height stands on its step as a whole number of sheets, as
    the cut model has it (see buildings.py); one without a height is left to the screen's own view.
    """
    out = []
    for step in terraces(terrain, interval_m):
        polygons = []
        for poly in _polygons(step.shape.simplify(tolerance, preserve_topology=True)):
            if poly.area < MIN_STEP_M2:
                continue
            poly = orient(poly, sign=1.0)
            polygons.append({"outline": _ring(poly.exterior.coords, digits),
                             "holes": [_ring(r.coords, digits) for r in poly.interiors if len(r.coords) >= 4]})
        if polygons:
            out.append({"level": step.level_m, "top": step.top, "bottom": step.bottom, "polygons": polygons})
    base, regions = layer_regions(terrain, interval_m)
    extent = affinity.translate(terrain.extent, *terrain.origin)
    stands = []
    for b in buildings:
        if b.top_z is None or not b.outline.intersects(extent):
            continue
        k, sheets = seat(b, base=base, interval=interval_m, datum=terrain.datum, layers=len(regions))
        bottom = base + k * interval_m - terrain.datum
        for part in _polygons(b.outline.intersection(extent)):
            part = orient(part, sign=1.0)
            stands.append({"outline": _ring(part.exterior.coords, digits),
                           "holes": [_ring(r.coords, digits) for r in part.interiors],
                           "bottom": round(bottom, 3), "top": round(bottom + sheets * interval_m, 3),
                           "sheets": sheets, "estimated": b.estimated})
    return {"interval": interval_m, "base_elev": out[0]["level"] if out else None, "datum": terrain.datum,
            "steps": out, "buildings": stands}
