"""
A model board laid on the ground: its size, the scale, where it sits, and how it is cut.

The designer picks the board (a paper size, a 우드락 sheet or their own size), the scale and the
material thickness, as a study model is planned: the board covers board mm × scale / 1000 m of
ground (the frame), which must lie inside the surroundings the site has (its range). `fit`
finds the standard scale at which the board covers as much of the range as it can, holding the
whole site.

Cutting (`cut`): each contour layer is cut from one board-size sheet, in place, so the sheets
stack straight and nothing has to be laid out; the buildings go on sheets of their own, laid
out by nesting.nest. `save_material` lays the layers above the base out as well, on fewer
sheets (a piece too big to lay out stays where it lies, on its layer's sheet). A laser bed smaller than the board cuts the model into modules first, as before
(pieces.module_grid), and lays every piece out on bed-size sheets.

Board sizes are millimetres (east–west, north–south as the board lies), the frame and the
centre are metres in the drawing table's frame.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point, Polygon, box

from sida.model_base.buildings import Building
from sida.model_base.nesting import Layout, Placement, nest
from sida.model_base.pieces import ModelPlan, fits, slice_terrain
from sida.model_base.terrain import Terrain

# key: (label, long side, short side) in mm
BOARDS = {
    "A0": ("A0", 1189.0, 841.0),
    "A1": ("A1", 841.0, 594.0),
    "A2": ("A2", 594.0, 420.0),
    "W600x900": ("우드락 600×900", 900.0, 600.0),
    "W900x1800": ("우드락 900×1800", 1800.0, 900.0),
}
CUSTOM = "custom"
SCALES = (100, 200, 250, 300, 400, 500, 600, 750, 1000, 1200, 1500, 2000)
THICKNESSES = (3.0, 5.0)
ORIENTS = ("landscape", "portrait")  # the long side east–west, or north–south
MIN_BOARD_MM, MAX_BOARD_MM = 100.0, 3000.0
MIN_SCALE, MAX_SCALE = 50, 5000
MIN_THICKNESS, MAX_THICKNESS = 0.5, 20.0
FIT_TRIES = 15  # centres tried along each side when the site's own middle does not fit


class FrameOutside(ValueError):
    """The board's frame reaches past the range by `overflow_m` metres."""

    def __init__(self, overflow_m: float):
        super().__init__(f"the board reaches {overflow_m:.0f} m past the surroundings")
        self.overflow_m = overflow_m


class NoFit(ValueError):
    """No standard scale lets the board hold the site and stay inside the range."""


def board_size(board: str, orient: str = "landscape", custom: tuple[float, float] | None = None) -> tuple[float, float]:
    """(east–west, north–south) mm of a board as it lies. `custom` (two sides in mm) is used for
    CUSTOM. Raises ValueError for an unknown board or orientation, or a custom size out of range."""
    if orient not in ORIENTS:
        raise ValueError(f"orient must be one of {', '.join(ORIENTS)}")
    if board == CUSTOM:
        if not custom or len(custom) != 2:
            raise ValueError("a custom board needs its width and height")
        a, b = (float(v) for v in custom)
        if not all(MIN_BOARD_MM <= v <= MAX_BOARD_MM for v in (a, b)):
            raise ValueError(f"a custom board is {MIN_BOARD_MM:g}–{MAX_BOARD_MM:g} mm a side")
        long, short = max(a, b), min(a, b)
    elif board in BOARDS:
        _, long, short = BOARDS[board]
    else:
        raise ValueError(f"board must be one of {', '.join([*BOARDS, CUSTOM])}")
    return (long, short) if orient == "landscape" else (short, long)


def check_scale(scale) -> int:
    value = int(scale)
    if value != scale or not MIN_SCALE <= value <= MAX_SCALE:
        raise ValueError(f"scale must be a whole number 1:{MIN_SCALE}–1:{MAX_SCALE}")
    return value


def check_thickness(thickness_mm) -> float:
    value = float(thickness_mm)
    if not MIN_THICKNESS <= value <= MAX_THICKNESS:
        raise ValueError(f"thickness must be {MIN_THICKNESS:g}–{MAX_THICKNESS:g} mm")
    return value


def frame_size(board_mm: tuple[float, float], scale: int) -> tuple[float, float]:
    """Metres of ground the board covers at 1:scale."""
    return board_mm[0] * scale / 1000.0, board_mm[1] * scale / 1000.0


def frame_box(center: tuple[float, float], frame_m: tuple[float, float]) -> Polygon:
    cx, cy = center
    w, h = frame_m
    return box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def overflow(frame: Polygon, range_outline: Polygon) -> float:
    """How far (m) the frame reaches past the range: the farthest corner's distance from it, 0
    when the frame lies inside (the range is a square, a rectangle or a circle: convex)."""
    return max(range_outline.distance(Point(c)) for c in frame.exterior.coords[:-1])


def check_frame(center: tuple[float, float], frame_m: tuple[float, float], range_outline: Polygon) -> Polygon:
    """The frame, if it lies inside the range; FrameOutside otherwise (by more than 1 cm)."""
    frame = frame_box(center, frame_m)
    over = overflow(frame, range_outline)
    if over > 0.01:
        raise FrameOutside(over)
    return frame


def fit(board_mm: tuple[float, float], range_outline: Polygon, site=None, *,
        scales: Sequence[int] = SCALES) -> dict:
    """
    The standard scale at which the board covers as much of the range as it can (the largest
    1:n whose frame still lies inside the range) while holding the whole site, and where it sits:
    {"scale", "center" [x, y], "frame_m" [w, h]}. The centre is the range's middle if the frame
    holds the site there, else the middle of the site's bounds, else the nearest spot that does
    both. Raises NoFit.
    """
    middle = range_outline.centroid
    if site is not None and not site.is_empty:
        sx0, sy0, sx1, sy1 = site.bounds
    else:
        sx0 = sx1 = middle.x
        sy0 = sy1 = middle.y
    want = ((sx0 + sx1) / 2, (sy0 + sy1) / 2)
    rx0, ry0, rx1, ry1 = range_outline.bounds
    for scale in sorted(scales, reverse=True):
        w, h = frame_size(board_mm, scale)
        if w < sx1 - sx0 or h < sy1 - sy0:
            continue
        if w > rx1 - rx0 + 0.02 or h > ry1 - ry0 + 0.02:  # wider than the range anywhere: no spot can hold it
            continue
        # the centres at which the frame still holds the site
        xs = np.linspace(sx1 - w / 2, sx0 + w / 2, FIT_TRIES)
        ys = np.linspace(sy1 - h / 2, sy0 + h / 2, FIT_TRIES)
        tries = sorted(((x, y) for x in xs for y in ys), key=lambda p: math.hypot(p[0] - want[0], p[1] - want[1]))
        for center in [(middle.x, middle.y), want, *tries]:
            frame = frame_box(center, (w, h))
            holds = site is None or site.is_empty or frame.buffer(0.01).contains(site)
            if holds and overflow(frame, range_outline) <= 0.01:
                return {"scale": int(scale), "center": [round(center[0], 2), round(center[1], 2)],
                        "frame_m": [round(w, 2), round(h, 2)]}
    raise NoFit("no standard scale lets the board hold the site inside the surroundings")


@dataclass
class BoardCut:
    model: ModelPlan
    layout: Layout
    in_place: bool  # each layer on a sheet of its own, where it lies on the board

    def summary(self) -> dict:
        top = max((p.layer for p in self.model.pieces), default=0)
        return {
            "interval": self.model.interval_m, "layers": len(self.model.layers), "sheets": self.layout.sheets,
            "pieces": len(self.model.pieces), "modules": len(self.model.modules),
            "buildings": len(self.model.buildings), "in_place": self.in_place,
            "total_height_mm": round((top + 1) * self.model.thickness_mm, 1),
            "size_mm": [round(v, 1) for v in self.model.size_mm],
            "utilisation": round(self.layout.utilisation(), 3),
        }


def cut(terrain: Terrain, *, scale: int, thickness_mm: float, board_mm: tuple[float, float],
        buildings: Sequence[Building] = (), bed_mm: tuple[float, float] | None = None,
        save_material: bool = False, gap: float = 2.0, margin: float = 5.0, res: float = 2.0,
        rotations: int = 4) -> BoardCut:
    """
    The board's layers and buildings as pieces on sheets (see the module's docstring). The
    terrain is the ground under the board (terrain.terrain_in_frame), so the model is the
    board's size.
    """
    w, h = board_mm
    if bed_mm is not None and not fits(w, h, *bed_mm):  # the bed takes the board in modules
        bw, bh = bed_mm
        model = slice_terrain(terrain, scale=scale, thickness_mm=thickness_mm,
                              room=(bw - 2 * margin - gap, bh - 2 * margin - gap), buildings=buildings)
        layout = nest(model.pieces, bw, bh, gap=gap, margin=margin, res=res, rotations=rotations)
        return BoardCut(model=model, layout=layout, in_place=False)
    model = slice_terrain(terrain, scale=scale, thickness_mm=thickness_mm, buildings=buildings)
    room_w, room_h = w - 2 * margin - gap - 3 * res, h - 2 * margin - gap - 3 * res  # nest grows pieces by a cell or so

    def stays(p) -> bool:  # cut where it lies: every ground piece, or the base and the ones too big to lay out
        if p.kind != "ground":
            return False
        if p.layer == 0 or not save_material:
            return True
        x0, y0, x1, y1 = p.shape.bounds
        return not fits(x1 - x0, y1 - y0, room_w, room_h)

    in_place = [p for p in model.pieces if stays(p)]
    kept = {id(p) for p in in_place}
    laid = [p for p in model.pieces if id(p) not in kept]
    sheet_of = {layer: n for n, layer in enumerate(sorted({p.layer for p in in_place}))}  # one sheet per layer
    placements = [Placement(piece=p, sheet=sheet_of[p.layer], angle=0.0, dx=0.0, dy=0.0) for p in in_place]
    first = sheets = len(sheet_of)
    if laid:
        rest = nest(laid, w, h, gap=gap, margin=margin, res=res, rotations=rotations)
        placements += [Placement(piece=p.piece, sheet=first + p.sheet, angle=p.angle, dx=p.dx, dy=p.dy)
                       for p in rest.placements]
        sheets += rest.sheets
    layout = Layout(sheet_w=w, sheet_h=h, margin=0.0, gap=gap, placements=placements, sheets=sheets)
    return BoardCut(model=model, layout=layout, in_place=True)
