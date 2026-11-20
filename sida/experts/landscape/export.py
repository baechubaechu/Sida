"""The landscape plan placed on the table as board_export layers (the CAD/Rhino export).

One layer per kind of ground (closed outlines on the ground, holes as their own outlines), the
path centre lines and the trees as crown circles. Nothing when no plan is placed.
"""

from __future__ import annotations

import math

from sida.experts.landscape import landscape

GROUP = "조경"
ZONES = {  # kind: (layer name, colour)
    "lawn": ("잔디", (130, 175, 95)),
    "shade": ("음지 지피", (95, 135, 105)),
    "hedge": ("관목 띠", (80, 120, 70)),
    "path": ("길", (190, 175, 150)),
    "plaza": ("광장(포장)", (200, 190, 170)),
    "paving": ("포장", (175, 170, 160)),
}
TREES = ("교목", (60, 120, 60))
PATH_LINES = ("길 중심선", (150, 130, 100))
CIRCLE = 16  # points of a crown


def _layer(short: str, color, curves: list) -> dict:
    return {"name": f"{GROUP} - {short}", "parent": GROUP, "color": color, "curves": curves}


def _ring(points) -> dict:
    return {"points": [[x, y, 0.0] for x, y in points], "closed": True}


def plan_layers(plan: dict) -> list[dict]:
    """A generator.generate plan as layers (empty kinds left out)."""
    out = []
    for kind, (short, color) in ZONES.items():
        curves = [_ring(r) for part in plan["zones"].get(kind, []) for r in [part["outer"], *part["holes"]]]
        if curves:
            out.append(_layer(short, color, curves))
    lines = [{"points": [[x, y, 0.0] for x, y in p["line"]], "closed": False} for p in plan["paths"] if len(p["line"]) >= 2]
    if lines:
        out.append(_layer(PATH_LINES[0], PATH_LINES[1], lines))
    crowns = []
    for t in plan["trees"]:
        steps = [2 * math.pi * i / CIRCLE for i in range(CIRCLE)]
        crowns.append(_ring([(round(t["x"] + t["r"] * math.cos(a), 2), round(t["y"] + t["r"] * math.sin(a), 2)) for a in steps]))
    if crowns:
        out.append(_layer(TREES[0], TREES[1], crowns))
    return out


def layers(project_dir) -> list[dict]:
    """The placed plan's layers, or [] when none is placed (or it cannot be worked out now)."""
    plan = landscape.placed_plan(project_dir)
    return plan_layers(plan) if plan else []
