#!/usr/bin/env python3
"""
Cut files for a contour model of the ground, laid out on your material.

    python scripts/model_base_terrain.py --sheet 600x400 --thickness 3 --scale 500 --out output/model_base

For now the ground is a made-up example (`--seed` picks one); surveyed ground comes later.
Writes, per sheet, a laser file (sheet-N.svg and .dxf: blue engrave, red inner cut, green outer
cut, run in that order) and a guide for people (sheet-N-guide.svg), plus assembly.svg (the
model from above, every piece in its place) and pieces.csv.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sida.model_base.output import (  # noqa: E402
    assembly_svg,
    guide_svg,
    piece_rows,
    sheet_dxf,
    sheet_svg,
)
from sida.model_base.pieces import HOLLOW_MODES  # noqa: E402
from sida.model_base.plan import cut_plan  # noqa: E402
from sida.model_base.terrain import example_terrain  # noqa: E402

HOLLOW_LABELS = {"none": "안 함", "all": "모든 층", "alternate": "한 층 걸러"}


def size(text: str) -> tuple[float, float]:
    w, _, h = text.lower().partition("x")
    return float(w), float(h)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sheet", default="600x400", help="material sheet, mm (width x height)")
    ap.add_argument("--thickness", type=float, default=3.0, help="material thickness, mm")
    ap.add_argument("--scale", type=int, default=500, help="model scale, 1:N")
    ap.add_argument("--area", default="240x180", help="ground to model, m (east-west x north-south)")
    ap.add_argument("--relief", type=float, default=16.0, help="example ground: highest minus lowest, m")
    ap.add_argument("--seed", type=int, default=7, help="which example ground")
    ap.add_argument("--hollow", choices=("auto", *HOLLOW_MODES), default="auto",
                    help="hollow the hidden middle of none, all or every other layer (auto: the fewest sheets)")
    ap.add_argument("--rim", type=float, default=8.0, help="rim kept under the next layer when hollowing, mm")
    ap.add_argument("--colors", default="", help="laser colours, e.g. engrave=#0000FF,inner=#FF0000,outer=#00A000")
    ap.add_argument("--gap", type=float, default=2.0, help="space between pieces, mm")
    ap.add_argument("--margin", type=float, default=5.0, help="unused edge of the sheet, mm")
    ap.add_argument("--rotations", type=int, default=8, help="orientations tried per piece")
    ap.add_argument("--res", type=float, default=1.0, help="layout grid, mm (smaller packs tighter, slower)")
    ap.add_argument("--out", default="output/model_base", help="folder for the files")
    a = ap.parse_args(argv)

    sheet_w, sheet_h = size(a.sheet)
    width_m, depth_m = size(a.area)
    started = time.time()
    terrain = example_terrain(a.seed, width_m=width_m, depth_m=depth_m, relief_m=a.relief)
    colors = dict(item.split("=", 1) for item in a.colors.split(",") if "=" in item)
    cut = cut_plan(terrain, sheet_w, sheet_h, scale=a.scale, thickness_mm=a.thickness,
                   hollow=HOLLOW_MODES if a.hollow == "auto" else a.hollow, hollow_rim_mm=a.rim,
                   gap=a.gap, margin=a.margin, res=a.res, rotations=a.rotations)
    plan, pieces, layout = cut.model, cut.pieces, cut.layout

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for n in range(layout.sheets):
        (out / f"sheet-{n + 1}.svg").write_text(sheet_svg(layout, n, colors), encoding="utf-8")
        (out / f"sheet-{n + 1}-guide.svg").write_text(guide_svg(layout, n, plan), encoding="utf-8")
        sheet_dxf(layout, n, out / f"sheet-{n + 1}.dxf")
    (out / "assembly.svg").write_text(assembly_svg(plan, layout), encoding="utf-8")
    rows = piece_rows(layout)
    with (out / "pieces.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    w, d = plan.size_mm
    print(f"{terrain.name}: {width_m:g}×{depth_m:g} m → 모형 {w:.0f}×{d:.0f} mm (1:{a.scale})")
    print(f"판 {a.thickness:g} mm = 등고 {plan.interval_m:g} m · 층 {len(plan.layers)}개 · 조각 {len(pieces)}개"
          + (f" (너무 작아 뺀 조각 {plan.dropped}개)" if plan.dropped else ""))
    print(f"재료 {sheet_w:g}×{sheet_h:g} mm 판 {layout.sheets}장 · 재료 사용률 {layout.utilisation() * 100:.0f}%"
          + f" · 속 비우기: {HOLLOW_LABELS[cut.hollow]}"
          + (" · 다음 층에 가려지는 선으로 나눔" if cut.hidden_cuts and any(p.tile for p in pieces) else "")
          + (" · 고리를 칼집으로 엶" if cut.opened else "")
          + (f" · 판보다 커서 나눈 이음 중 보이는 길이 {cut.seam_mm:g} mm" if cut.seam_mm else "")
          + f" · {time.time() - started:.1f}초")
    print(f"파일: {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
