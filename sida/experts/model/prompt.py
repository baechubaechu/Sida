"""
The model maker's facts: what Sida's code works out for each board, so the expert chooses
among numbers and never makes one up.

For the project's site and its saved 3D range: the site's area and size, the range, the
ground's relief in it, and for each board (sida/model_base/board.BOARDS) and thickness
(THICKNESSES) the scale at which the board covers as much of the range as it can (board.fit,
in the orientation that covers more), the ground it then covers, the layers it takes (each a
sheet, cut in place) and how big the site reads on it. Without a site or a terrain pack the
block says what is missing.
"""

from __future__ import annotations

import math

import numpy as np

from sida.experts import FACTS, ExpertRun, PromptBlock
from sida.experts.model import model_base
from sida.model_base import board

HEADER = "## Board Options (computed by Sida; use only these numbers)"
SHAPES_EN = {"square": "square", "circle": "circle", "rect": "rectangle"}


def _site_plan(project_dir):
    from sida.board import site_plan
    from sida.experts.site import site_facts

    facts = site_facts.load_facts(project_dir)
    if not facts:
        return None, None
    summary = site_facts.board_summary(facts)
    return site_plan(summary["parcels"]), summary.get("area_m2")


def _layers(g: dict, center, frame_m, interval: float) -> int | None:
    """Layers the ground under the frame takes (pieces.layer_regions counts the same way)."""
    n = g["grid"].shape[0]
    axis = -g["half"] + g["step"] * np.arange(n)
    cols = np.flatnonzero(np.abs(axis - center[0]) <= frame_m[0] / 2)
    rows = np.flatnonzero(np.abs(axis - center[1]) <= frame_m[1] / 2)
    if not len(cols) or not len(rows):
        return None
    z = g["grid"][np.ix_(rows, cols)] + g["ground_elev"]
    lo, hi = float(z.min()), float(z.max())
    base = math.floor(lo / interval + 1e-9) * interval
    return max(1, math.ceil((hi - base) / interval - 1e-9))


def options(plan: dict, picked: dict, *, folder=None) -> list[dict]:
    """For each board and thickness, the fitted scale in the better orientation and what it gives."""
    g = model_base._ground(plan, picked["radius"], folder)
    site = model_base._site(plan)
    x0, y0, x1, y1 = site.bounds if site is not None else (0, 0, 0, 0)
    out = []
    for key, (label, _long, _short) in board.BOARDS.items():
        for thickness in board.THICKNESSES:
            best = None
            for orient in board.ORIENTS:
                try:
                    got = model_base.fit_board(plan, radius=picked["radius"], shape=picked["shape"],
                                               range_orient=picked["orient"], board_name=key, orient=orient)
                except ValueError:
                    continue
                if best is None or got["scale"] > best["scale"]:
                    best = {**got, "orient": orient}
            if best is None:
                out.append({"board": key, "label": label, "thickness": thickness, "fits": False})
                continue
            interval = thickness * best["scale"] / 1000
            layers = _layers(g, best["center"], best["frame_m"], interval)
            out.append({
                "board": key, "label": label, "thickness": thickness, "fits": True, "orient": best["orient"],
                "scale": best["scale"], "frame_m": best["frame_m"], "board_mm": best["board_mm"],
                "interval_m": round(interval, 3), "layers": layers, "ground_sheets": layers,
                "height_mm": round(layers * thickness, 1) if layers else None,
                "site_cm": [round((x1 - x0) * 100 / best["scale"], 1), round((y1 - y0) * 100 / best["scale"], 1)],
            })
    return out


def board_facts(run: ExpertRun) -> PromptBlock:
    from sida.experts.site import context3d, context_range

    plan, area = _site_plan(run.project_dir)
    if plan is None:
        return PromptBlock(f"{HEADER}\n\nNo site has been looked up for this project, so no board can be laid "
                           "on it yet. Ask the designer to look the site up and load its 3D surroundings.", FACTS)
    picked = context_range.load(run.project_dir)
    hx, hy = context3d.half_sides(picked["radius"], context3d.range_key(picked["shape"], picked["orient"]))
    site = model_base._site(plan)
    lines = [HEADER, ""]
    if site is not None:
        sx0, sy0, sx1, sy1 = site.bounds
        lines.append(f"- Site: {f'{area:.0f} m², ' if area else ''}{sx1 - sx0:.0f} × {sy1 - sy0:.0f} m (east–west × north–south)")
    shape = SHAPES_EN.get(picked["shape"], picked["shape"])
    turned = f", {picked['orient']}" if picked["shape"] == "rect" else ""
    size = f"radius {picked['radius']:.0f} m" if picked["shape"] == "circle" else f"{2 * hx:.0f} × {2 * hy:.0f} m"
    lines.append(f"- 3D range loaded: {picked['size']} {shape}{turned}, {size}")
    try:
        rows = options(plan, picked)
        g = model_base._ground(plan, picked["radius"], None)
    except model_base.NoTerrain:
        lines.append("- Ground: no terrain pack covers this site, so the layers cannot be worked out. "
                     "Say so and recommend nothing numeric.")
        return PromptBlock("\n".join(lines), FACTS)
    z = g["grid"] + g["ground_elev"]
    lines.append(f"- Ground in the range: {float(z.min()):.1f}–{float(z.max()):.1f} m above sea level "
                 f"(relief {float(z.max() - z.min()):.1f} m)")
    lines += ["", "| board key | board | orientation | thickness (mm) | scale | ground covered (m) | step per sheet (m) "
              "| layers | ground sheets | ground height (mm) | site on the board (cm) |", "|" + "---|" * 11]
    for r in rows:
        if not r["fits"]:
            lines.append(f"| {r['board']} | {r['label']} | – | {r['thickness']:g} | no standard scale fits | | | | | | |")
            continue
        lines.append(f"| {r['board']} | {r['label']} | {r['orient']} | {r['thickness']:g} | 1:{r['scale']} "
                     f"| {r['frame_m'][0]:.0f} × {r['frame_m'][1]:.0f} | {r['interval_m']:g} | {r['layers']} "
                     f"| {r['ground_sheets']} | {r['height_mm']} | {r['site_cm'][0]} × {r['site_cm'][1]} |")
    lines += ["", "Each layer is cut in place from one board-size sheet. Buildings come on sheets of their own; "
              "their count is not known until the designer presses 계산하기 (calculate) on the model board panel."]
    return PromptBlock("\n".join(lines), FACTS)
