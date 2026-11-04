"""
Pieces laid out on sheets of material with as little waste as practical.

Each piece is drawn on a grid (`res` mm cells), grown by half the gap plus one cell so pieces
never come closer than `gap` once cut, and tried in `rotations` orientations. Biggest pieces go
first (by the room their outline takes, not their area: a ring takes its whole hull); each goes to the lowest, then leftmost, free spot over all orientations on the first
sheet that has room (found for every spot at once by an FFT correlation of the sheet's filled
cells with the piece's cells). Holes inside pieces count as free, so small pieces can go in them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon

from sida.model_base.pieces import Piece


@dataclass
class Placement:
    piece: Piece
    sheet: int  # 0-based
    angle: float  # degrees, counter-clockwise about the piece's own origin
    dx: float
    dy: float

    def place(self, geom):
        """A geometry of the piece (its outline, a line on it) where it lies on its sheet."""
        return affinity.translate(affinity.rotate(geom, self.angle, origin=(0, 0)), self.dx, self.dy)

    def place_point(self, xy: tuple[float, float]) -> tuple[float, float]:
        a = np.radians(self.angle)
        x, y = xy
        return (x * np.cos(a) - y * np.sin(a) + self.dx, x * np.sin(a) + y * np.cos(a) + self.dy)


@dataclass
class Layout:
    sheet_w: float
    sheet_h: float
    margin: float
    gap: float
    placements: list[Placement]
    sheets: int

    def on_sheet(self, n: int) -> list[Placement]:
        return [p for p in self.placements if p.sheet == n]

    def utilisation(self) -> float:
        used = sum(p.piece.area for p in self.placements)
        return used / max(1e-9, self.sheets * self.sheet_w * self.sheet_h)


class DoesNotFit(ValueError):
    pass


def rasterize(poly: Polygon, res: float, shape: tuple[int, int]) -> np.ndarray:
    """Cells (rows from y = 0 up, columns from x = 0) whose centres are inside `poly` (even-odd)."""
    rows, cols = shape
    grid = np.zeros(shape, dtype=bool)
    rings = [np.asarray(poly.exterior.coords)] + [np.asarray(r.coords) for r in poly.interiors]
    edges = np.concatenate([np.stack([r[:-1], r[1:]], axis=1) for r in rings])  # (n, 2, 2)
    (xa, ya), (xb, yb) = edges[:, 0].T, edges[:, 1].T
    centres_x = (np.arange(cols) + 0.5) * res
    for row in range(rows):
        y = (row + 0.5) * res
        cross = (ya <= y) != (yb <= y)
        if not cross.any():
            continue
        t = (y - ya[cross]) / (yb[cross] - ya[cross])
        xs = np.sort(xa[cross] + t * (xb[cross] - xa[cross]))
        for left, right in zip(xs[0::2], xs[1::2], strict=False):
            grid[row] |= (centres_x >= left) & (centres_x <= right)
    return grid


def _variants(piece: Piece, rotations: int, res: float, grow: float):
    """The piece in each orientation: (angle, offset to put its grown bounds at 0,0, cells)."""
    out = []
    seen = set()
    for i in range(rotations):
        angle = round(i * 360 / rotations, 6)
        rotated = affinity.rotate(piece.shape, angle, origin=(0, 0))
        grown = rotated.buffer(grow, join_style=2)
        x0, y0, x1, y1 = grown.bounds
        shape = (int(np.ceil((y1 - y0) / res)), int(np.ceil((x1 - x0) / res)))
        cells = np.zeros(shape, dtype=bool)
        for part in getattr(grown, "geoms", [grown]):
            cells |= rasterize(affinity.translate(part, -x0, -y0), res, shape)
        key = (shape, cells.tobytes())
        if key in seen:  # a symmetric piece looks the same turned
            continue
        seen.add(key)
        out.append((angle, (-x0, -y0), cells))
    return out


def nest(pieces: list[Piece], sheet_w: float, sheet_h: float, *, gap: float = 2.0, margin: float = 5.0,
         res: float = 1.0, rotations: int = 8) -> Layout:
    """Lay every piece on as few sheets as it takes. Raises DoesNotFit for a piece no sheet can hold."""
    if sheet_w <= 2 * margin or sheet_h <= 2 * margin:
        raise ValueError("the sheet is smaller than its margins")
    rows, cols = int(sheet_h // res), int(sheet_w // res)
    edge = int(np.ceil(margin / res))

    def empty_sheet():
        occ = np.ones((rows, cols), dtype=bool)
        occ[edge:rows - edge, edge:cols - edge] = False
        return occ

    sheets: list[np.ndarray] = []
    placements: list[Placement] = []
    grow = gap / 2 + res
    for piece in sorted(pieces, key=lambda p: -p.shape.convex_hull.area):  # the most room-taking first
        variants = _variants(piece, rotations, res, grow)
        placed = False
        for n in range(len(sheets) + 1):
            if n == len(sheets):
                sheets.append(empty_sheet())
            occ = sheets[n]
            occ_f = np.fft.rfft2(occ.astype(np.float64))
            best = None
            for angle, (ox, oy), cells in variants:
                h, w = cells.shape
                if h > rows or w > cols:
                    continue
                kernel = np.zeros((rows, cols))
                kernel[:h, :w] = cells
                hits = np.fft.irfft2(occ_f * np.conj(np.fft.rfft2(kernel)), s=(rows, cols))
                free = hits[: rows - h + 1, : cols - w + 1] < 0.5
                if not free.any():
                    continue
                r = int(np.argmax(free.any(axis=1)))  # lowest row with room
                c = int(np.argmax(free[r]))
                score = (r + h, c)
                if best is None or score < best[0]:
                    best = (score, r, c, angle, ox, oy, cells)
            if best is None:
                if n == len(sheets) - 1 and not occ[edge:rows - edge, edge:cols - edge].any():
                    sheets.pop()
                    raise DoesNotFit(f"piece {piece.id} does not fit on a {sheet_w:g} × {sheet_h:g} mm sheet")
                continue
            _, r, c, angle, ox, oy, cells = best
            h, w = cells.shape
            occ[r:r + h, c:c + w] |= cells
            placements.append(Placement(piece=piece, sheet=n, angle=angle, dx=c * res + ox, dy=r * res + oy))
            placed = True
            break
        assert placed
    return Layout(sheet_w=sheet_w, sheet_h=sheet_h, margin=margin, gap=gap, placements=placements, sheets=len(sheets))
