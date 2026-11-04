"""The ground as a height grid in metres (x east, y north), with the site on it."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, box


@dataclass(frozen=True)
class Terrain:
    xs: np.ndarray  # metres, west to east
    ys: np.ndarray  # metres, south to north
    z: np.ndarray  # metres, shape (len(ys), len(xs))
    site: Polygon | None = None  # the site boundary in the same metres
    name: str = ""

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
