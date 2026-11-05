"""
The ground as a height grid in metres (x east, y north), with the site on it.

`terrain_from_grid` takes the ground the drawing table already computes for a site (a square
height grid around the site's middle, see sida/experts/site/context3d.py) and cuts out the
part to model; `example_terrain` makes up a ground for trying the layout without one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

AREA_KINDS = ("road", "sidewalk", "water")  # what parts of the ground are, engraved on the model


@dataclass(frozen=True)
class Terrain:
    xs: np.ndarray  # metres, west to east
    ys: np.ndarray  # metres, south to north
    z: np.ndarray  # metres, shape (len(ys), len(xs))
    site: Polygon | None = None  # the site boundary in the same metres
    name: str = ""
    # What parts of the ground are (AREA_KINDS): one shape per kind, within the extent.
    areas: tuple[tuple[str, Polygon | MultiPolygon], ...] = ()

    @property
    def extent(self) -> Polygon:
        return box(float(self.xs[0]), float(self.ys[0]), float(self.xs[-1]), float(self.ys[-1]))


def example_terrain(seed: int = 0, *, width_m: float = 240, depth_m: float = 180,
                    cell_m: float = 2.0, relief_m: float = 16.0) -> Terrain:
    """
    A made-up but plausible ground for trying the cutting layout: a gentle slope, a few hills
    and hollows, and a four-sided site near the middle. The same seed gives the same ground.
    Not a real place: use it only where no surveyed ground is at hand.
    """
    rng = np.random.default_rng(seed)
    xs = np.arange(0.0, width_m + cell_m / 2, cell_m)
    ys = np.arange(0.0, depth_m + cell_m / 2, cell_m)
    x, y = np.meshgrid(xs, ys)
    angle = rng.uniform(0, 2 * np.pi)
    z = 0.35 * relief_m * ((x - width_m / 2) * np.cos(angle) + (y - depth_m / 2) * np.sin(angle)) / max(width_m, depth_m)
    for _ in range(rng.integers(3, 6)):
        cx, cy = rng.uniform(0, width_m), rng.uniform(0, depth_m)
        spread = rng.uniform(0.12, 0.3) * max(width_m, depth_m)
        height = rng.uniform(-0.5, 1.0) * relief_m
        z += height * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * spread**2))
    for _ in range(3):  # long, soft undulations
        k = rng.uniform(0.5, 1.6) * 2 * np.pi / max(width_m, depth_m)
        phase = rng.uniform(0, 2 * np.pi)
        d = rng.uniform(0, 2 * np.pi)
        z += 0.06 * relief_m * np.sin(k * (x * np.cos(d) + y * np.sin(d)) + phase)
    z -= z.min()
    z *= relief_m / max(z.max(), 1e-9)

    w, d = rng.uniform(38, 55), rng.uniform(28, 42)
    cx = width_m * rng.uniform(0.42, 0.58)
    cy = depth_m * rng.uniform(0.42, 0.58)
    corners = [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]
    corners = [(px + rng.uniform(-3, 3), py + rng.uniform(-3, 3)) for px, py in corners]
    site = affinity.rotate(Polygon(corners), rng.uniform(-35, 35), origin=(0, 0))
    site = affinity.translate(site, cx, cy)
    return Terrain(xs=xs, ys=ys, z=z, site=site, name=f"예시 지형 {seed}")


def _polygon(shape) -> Polygon | None:
    if shape is None:
        return None
    poly = shape if isinstance(shape, Polygon) else Polygon(np.asarray(shape, dtype=float))
    poly = poly.buffer(0)
    return poly if not poly.is_empty else None


def terrain_from_grid(grid, half: float, step: float, *, width_m: float, depth_m: float,
                      base_elev: float = 0.0, site=None, areas=(), name: str = "") -> Terrain:
    """
    The part of a square height grid to model: `width_m` × `depth_m` around the grid's middle.

    `grid` is (n × n) heights in metres from -half to +half, `step` apart (rows south to north,
    columns west to east), relative to `base_elev` (the height above sea level at the middle),
    as the drawing table's ground is. The model keeps heights above sea level, so its contour
    layers fall on round heights. `site` is the site boundary and `areas` are (kind, ring)
    pairs of what the ground is (AREA_KINDS; other kinds are left out), both as polygons or
    rings of points in the grid's metres. The model's own (0, 0) is its south-west corner.
    """
    if grid is None:
        raise ValueError("no ground for this site")
    z = np.asarray(grid, dtype=float)
    if z.ndim != 2 or z.shape[0] != z.shape[1] or z.shape[0] < 2:
        raise ValueError("the ground grid must be square")
    if width_m <= 0 or depth_m <= 0:
        raise ValueError("the area to model must have a size")
    axis = -half + step * np.arange(z.shape[0])
    if width_m / 2 > axis[-1] + 1e-6 or depth_m / 2 > axis[-1] + 1e-6:
        raise ValueError(f"the ground reaches {axis[-1]:g} m from the middle, less than the area to model")
    cols = np.flatnonzero(np.abs(axis) <= width_m / 2 + 1e-6)
    rows = np.flatnonzero(np.abs(axis) <= depth_m / 2 + 1e-6)
    x0, y0 = float(axis[cols[0]]), float(axis[rows[0]])
    xs, ys = axis[cols] - x0, axis[rows] - y0
    heights = z[np.ix_(rows, cols)] + float(base_elev)
    extent = box(0.0, 0.0, float(xs[-1]), float(ys[-1]))

    def place(shape):
        poly = _polygon(shape)
        return affinity.translate(poly, -x0, -y0) if poly is not None else None

    site_poly = place(site)
    kinds: dict[str, list[Polygon]] = {}
    for kind, ring in areas:
        poly = place(ring) if kind in AREA_KINDS else None
        if poly is not None:
            kinds.setdefault(kind, []).append(poly)
    shapes = []
    for kind in AREA_KINDS:
        if kind in kinds:
            shape = unary_union(kinds[kind]).intersection(extent)
            if not shape.is_empty:
                shapes.append((kind, shape))
    return Terrain(xs=xs, ys=ys, z=heights, site=site_poly, name=name, areas=tuple(shapes))
