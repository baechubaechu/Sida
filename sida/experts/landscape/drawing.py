"""A landscape plan as a drawing instruction for the Rhino plugin (docs/rhino-api.md, "다이어그램"):
the ground kinds as fills, the path centre lines, the trees as crown circles in plan and as `tree`
items the plugin stands up (a round crown on a trunk). The drawing is laid where it is
(`in_place`: the snapshot's frame is the document's), on sublayers of "Sida 조경".
"""

from __future__ import annotations

import math

from sida.experts.landscape import generator

LAYER = "Sida 조경"
ZONES = {  # kind: (sublayer, colour), drawn bottom first
    "paving": ("포장", "#d8d2c4"),
    "plaza": ("광장(포장)", "#e6dcc6"),
    "path": ("길", "#cfc2a6"),
    "lawn": ("잔디·초화", "#a9c98a"),
    "shade": ("음지 지피", "#7fa88a"),
    "hedge": ("관목 띠", "#6f9a5e"),
}
TREE_COLORS = {"sun": "#6f9f58", "shade": "#4f7f62", "planter": "#7aa060"}
TREE_HEIGHT = {"sun": 6.5, "shade": 6.5, "planter": 5.0}  # m, a young street-size tree
PATH_INK = "#8a7a62"
CIRCLE = 16  # points of a crown in plan
STATE = {True: "맞음", False: "모자람", None: "참고"}


def _r(v: float) -> float:
    return round(float(v), 3)


def check_lines(plan: dict) -> list[str]:
    """"맞음 조경면적 645㎡ / 152㎡ 이상" for each check of the plan."""
    out = []
    for c in plan.get("checks") or []:
        need = f" / {c['need']}" if c.get("need") and c["need"] != "-" else ""
        out.append(f"{STATE[c['ok']]} {c['title']} {c['value']}{need}")
    return out


def drawing(plan: dict) -> dict:
    """The plan (generator.generate + "checks") as a drawing instruction."""
    items: list[dict] = []
    for kind, (layer, color) in ZONES.items():
        for part in plan["zones"].get(kind, []):
            rings = [[[_r(x), _r(y)] for x, y in ring] for ring in [part["outer"], *part["holes"]]]
            items.append({"type": "fill", "rings": rings, "z": 0.0, "color": color, "light": False, "role": "", "layer": layer})
    for path in plan["paths"]:
        if len(path["line"]) >= 2:
            items.append({"type": "line", "points": [[_r(x), _r(y), 0.02] for x, y in path["line"]], "closed": False, "bold": False,
                          "dashed": True, "color": PATH_INK, "layer": "길 중심선"})
    for t in plan["trees"]:
        steps = [2 * math.pi * i / CIRCLE for i in range(CIRCLE)]
        items.append({"type": "line", "points": [[_r(t["x"] + t["r"] * math.cos(a)), _r(t["y"] + t["r"] * math.sin(a)), 0.05] for a in steps],
                      "closed": True, "bold": False, "dashed": False, "color": TREE_COLORS[t["kind"]], "layer": "교목 평면"})
        items.append({"type": "tree", "at": [_r(t["x"]), _r(t["y"]), 0.0], "r": _r(t["r"]), "height": TREE_HEIGHT[t["kind"]],
                      "color": TREE_COLORS[t["kind"]], "layer": "교목"})
    knobs = generator.Tune.read(plan.get("tune")).words()
    return {"kind": "landscape", "title": " · ".join(["자동 조경", plan["label"], *knobs]), "view": "flat", "layer": LAYER, "in_place": True,
            "bounds": _extent(items), "items": items, "notes": check_lines(plan)}


def _extent(items: list[dict]) -> list[float]:
    xs, ys, zs = [], [], [0.0]
    for item in items:
        if item["type"] == "fill":
            for ring in item["rings"]:
                xs += [p[0] for p in ring]
                ys += [p[1] for p in ring]
        elif item["type"] == "line":
            xs += [p[0] for p in item["points"]]
            ys += [p[1] for p in item["points"]]
        elif item["type"] == "tree":
            xs.append(item["at"][0])
            ys.append(item["at"][1])
            zs.append(item["height"])
    if not xs:
        return [0.0] * 6
    return [_r(v) for v in (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))]
