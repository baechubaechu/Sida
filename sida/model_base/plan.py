"""From ground and material to a cutting layout, trying which layers to hollow."""

from __future__ import annotations

from dataclasses import dataclass

from sida.model_base.nesting import Layout, nest
from sida.model_base.pieces import (
    HOLLOW_MODES,
    ModelPlan,
    Piece,
    open_rings,
    slice_terrain,
    split_hidden,
    split_to_fit,
)
from sida.model_base.terrain import Terrain


@dataclass
class CutPlan:
    model: ModelPlan
    pieces: list[Piece]
    layout: Layout
    hollow: str
    opened: bool  # rings opened by one cut each (see pieces.open_rings)
    hidden_cuts: bool  # big pieces cut only where the next layer hides the joint (pieces.split_hidden)

    @property
    def seam_mm(self) -> float:
        """Length of cuts through the pieces (to fit a sheet, to open a ring) that shows on the model."""
        seen = {}
        for p in self.pieces:
            key = p.id[:3] if p.tile else p.id  # the parts of a cut piece share its seams
            seen[key] = max(seen.get(key, 0.0), p.seam_mm)
        return round(sum(seen.values()), 1)


def cut_plan(terrain: Terrain, sheet_w: float, sheet_h: float, *, scale: int = 500, thickness_mm: float = 3.0,
             hollow: str | tuple[str, ...] = HOLLOW_MODES, hollow_rim_mm: float = 8.0, open_ring: tuple[bool, ...] = (False, True),
             hidden_cuts: tuple[bool, ...] = (False, True), gap: float = 2.0, margin: float = 5.0, res: float = 1.0, rotations: int = 8) -> CutPlan:
    """
    The layout with the fewest sheets over the hollowing modes, ring opening and hidden cuts
    asked (all by default). A layout whose cuts show nowhere on the model wins over any that
    shows a joint; then the fewest sheets, the least joint showing, the fewest pieces.
    """
    modes = (hollow,) if isinstance(hollow, str) else tuple(hollow)
    room = (sheet_w - 2 * margin - gap, sheet_h - 2 * margin - gap)
    best = None
    for mode in modes:
        model = slice_terrain(terrain, scale=scale, thickness_mm=thickness_mm, hollow=mode, hollow_rim_mm=hollow_rim_mm)
        for hidden in hidden_cuts:
            base = split_hidden(model.pieces, 0.3 * sheet_w * sheet_h) if hidden else model.pieces
            whole = split_to_fit(base, *room)
            for opened in open_ring:
                if opened and not any(p.holed for p in whole):
                    continue
                pieces = open_rings(whole) if opened else whole
                layout = nest(pieces, sheet_w, sheet_h, gap=gap, margin=margin, res=res, rotations=rotations)
                plan = CutPlan(model=model, pieces=pieces, layout=layout, hollow=mode, opened=opened, hidden_cuts=hidden)
                key = (plan.seam_mm > 0, layout.sheets, plan.seam_mm, len(pieces))  # a joint that shows is worst
                if best is None or key < best[0]:
                    best = (key, plan)
    return best[1]
