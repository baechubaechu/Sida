"""From ground and material to a cutting layout."""

from __future__ import annotations

from dataclasses import dataclass

from sida.model_base.nesting import Layout, nest
from sida.model_base.pieces import ModelPlan, slice_terrain
from sida.model_base.terrain import Terrain


@dataclass
class CutPlan:
    model: ModelPlan
    layout: Layout

    @property
    def pieces(self):
        return self.model.pieces


def cut_plan(terrain: Terrain, sheet_w: float, sheet_h: float, *, scale: int = 500, thickness_mm: float = 3.0,
             hollow_rim_mm: float = 0.0, gap: float = 2.0, margin: float = 5.0, res: float = 1.0,
             rotations: int = 8) -> CutPlan:
    """The model cut into as few modules as the sheet needs, its layer pieces laid on sheets."""
    room = (sheet_w - 2 * margin - gap, sheet_h - 2 * margin - gap)
    model = slice_terrain(terrain, scale=scale, thickness_mm=thickness_mm, room=room, hollow_rim_mm=hollow_rim_mm)
    layout = nest(model.pieces, sheet_w, sheet_h, gap=gap, margin=margin, res=res, rotations=rotations)
    return CutPlan(model=model, layout=layout)
