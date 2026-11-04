"""From ground and material to a cutting layout, trying how finely to cut the thin rims."""

from __future__ import annotations

from dataclasses import dataclass

from sida.model_base.nesting import Layout, nest
from sida.model_base.pieces import ModelPlan, Piece, slice_terrain, split_to_fit
from sida.model_base.terrain import Terrain

# Rim tile sizes tried, mm (None: rims kept whole). Finer tiles pack tighter but make more
# pieces to glue, so the fewest sheets win and, among those, the fewest pieces.
CHUNKS = (None, 250.0, 200.0, 150.0, 120.0)


@dataclass
class CutPlan:
    model: ModelPlan
    pieces: list[Piece]
    layout: Layout
    chunk: float | None


def cut_plan(terrain: Terrain, sheet_w: float, sheet_h: float, *, scale: int = 500, thickness_mm: float = 3.0,
             hollow_rim_mm: float = 8.0, gap: float = 2.0, margin: float = 5.0, res: float = 1.0,
             rotations: int = 8, chunks=CHUNKS) -> CutPlan:
    model = slice_terrain(terrain, scale=scale, thickness_mm=thickness_mm, hollow_rim_mm=hollow_rim_mm)
    room = (sheet_w - 2 * margin - gap, sheet_h - 2 * margin - gap)
    best = None
    for chunk in chunks:
        pieces = split_to_fit(model.pieces, *room, chunk=chunk)
        layout = nest(pieces, sheet_w, sheet_h, gap=gap, margin=margin, res=res, rotations=rotations)
        key = (layout.sheets, len(pieces))
        if best is None or key < best[0]:
            best = (key, CutPlan(model=model, pieces=pieces, layout=layout, chunk=chunk))
    return best[1]
