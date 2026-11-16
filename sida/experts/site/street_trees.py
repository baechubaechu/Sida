"""Street trees around the site, set out by a rule (for the picture, not where real trees stand).

No file the app may use says where each street tree is: 서울시 가로수 위치정보 is 공공누리 제4유형
(no commercial use, no changes), so it is not read. Instead a tree is drawn along the kerb of
each sidewalk area the packs have (수치지형도 보도, 정밀도로지도 보도), by this rule:

- KERB_INSET m in from the sidewalk's edge, on the edge that runs along a road (a road area within
  KERB_INSET + KERB_GAP m), every SPACING m;
- not within CLEAR_OF_BUILDINGS m of a building, not on water, not on a sidewalk smaller than
  MIN_SIDEWALK m², and never two closer than SPACING × 0.75;
- standing on the drawn ground, HEIGHT m tall with a crown CROWN m across.

The screen and the files say these are 표현용 (where trees would go, not a survey). Independent of
HTTP and the screen; points are in the table's frame (metres, x east, y north).
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

SPACING = 8.0  # m between trees along a kerb
KERB_INSET = 1.2  # m from the sidewalk's edge to a trunk
KERB_GAP = 0.8  # m the files may leave between a sidewalk and its road
CLEAR_OF_BUILDINGS = 2.0  # m from a building's outline
MIN_SIDEWALK = 20.0  # m², smaller sidewalk pieces get no trees
HEIGHT = 8.0  # m, a tree's top above the ground
CROWN = 5.2  # m across the crown
RULE = (f"인도의 도로 쪽 가장자리에서 {KERB_INSET:g} m 안쪽, {SPACING:g} m 간격, 건물에서 {CLEAR_OF_BUILDINGS:g} m 이상, "
        f"높이 {HEIGHT:g} m (실제 나무 위치가 아닌 표현용)")


def _polygon(ring) -> Polygon | None:
    pts = np.asarray(ring, dtype=float)
    if len(pts) < 3:
        return None
    p = Polygon(pts)
    if not p.is_valid:
        p = p.buffer(0)
    return p if not p.is_empty else None


def _union(rings) -> object:
    polys = [p for p in (_polygon(r) for r in rings) if p is not None]
    return unary_union(polys) if polys else None


def place(areas: list[tuple[str, object]], outlines: list, *, spacing: float = SPACING) -> list[tuple[float, float]]:
    """
    Where the trees stand, [(x, y)], from the ground areas [(kind, ring)] (kinds as in
    terrain_pack.KINDS) and the building outlines [ring]. Empty when there is no sidewalk or road.
    """
    sidewalks = [p for kind, ring in areas if kind == "sidewalk" and (p := _polygon(ring)) is not None]
    roads = _union(ring for kind, ring in areas if kind == "road")
    if not sidewalks or roads is None:
        return []
    water = _union(ring for kind, ring in areas if kind == "water")
    blocked = _union(outlines)
    blocked = blocked.buffer(CLEAR_OF_BUILDINGS) if blocked is not None else None
    if water is not None:
        blocked = water if blocked is None else blocked.union(water)
    kerb = roads.buffer(KERB_INSET + KERB_GAP)
    kept: list[tuple[float, float]] = []
    near = spacing * 0.75
    cells: dict[tuple[int, int], list[tuple[float, float]]] = {}

    def crowded(x: float, y: float) -> bool:
        ci, cj = int(np.floor(x / near)), int(np.floor(y / near))
        return any((x - a) ** 2 + (y - b) ** 2 < near * near
                   for di in (-1, 0, 1) for dj in (-1, 0, 1) for a, b in cells.get((ci + di, cj + dj), ()))

    for walk in sidewalks:
        for piece in getattr(walk, "geoms", [walk]):
            if piece.geom_type != "Polygon" or piece.area < MIN_SIDEWALK:
                continue
            inner = piece.buffer(-KERB_INSET)
            for part in getattr(inner, "geoms", [inner]):
                if part.is_empty or part.geom_type != "Polygon":
                    continue
                edge = part.exterior
                for k in range(int(edge.length // spacing)):
                    pt = edge.interpolate(k * spacing + spacing / 2)
                    if not kerb.contains(pt) or (blocked is not None and blocked.contains(pt)):
                        continue
                    x, y = round(pt.x, 2), round(pt.y, 2)
                    if crowded(x, y):
                        continue
                    kept.append((x, y))
                    cells.setdefault((int(np.floor(x / near)), int(np.floor(y / near))), []).append((x, y))
    return kept

