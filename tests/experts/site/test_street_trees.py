"""Street trees set out by street_trees' rule, and how the surroundings carry them."""

from __future__ import annotations

import math

import pytest

from sida.experts.site import context3d, street_trees


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# A road along y = 0..10, a 4 m sidewalk north of it (y = 10..14), a building north of that.
ROAD = ("road", rect(-100, 0, 100, 10))
WALK = ("sidewalk", rect(-100, 10, 100, 14))


def test_trees_stand_along_the_kerb_at_the_spacing():
    spots = street_trees.place([ROAD, WALK], [])
    assert spots
    ys = {round(y, 2) for _, y in spots}
    assert ys == {10 + street_trees.KERB_INSET}  # the kerb side only, not the far edge (y = 12.8)
    xs = sorted(x for x, _ in spots)
    gaps = [b - a for a, b in zip(xs, xs[1:], strict=False)]
    assert min(gaps) >= street_trees.SPACING * 0.75 and max(gaps) == pytest.approx(street_trees.SPACING, abs=0.01)


def test_no_trees_by_buildings_on_water_or_without_a_road():
    building = rect(-20, 13, 20, 40)  # comes down to the sidewalk
    spots = street_trees.place([ROAD, WALK], [building])
    assert spots and all(abs(x) > 20 + street_trees.CLEAR_OF_BUILDINGS - 0.01 for x, _ in spots)
    water = ("water", rect(40, 5, 100, 20))
    assert all(x < 40 for x, _ in street_trees.place([ROAD, WALK, water], []))
    assert street_trees.place([WALK], []) == []  # a sidewalk with no road beside it
    assert street_trees.place([ROAD, ("sidewalk", rect(0, 10, 4, 14))], []) == []  # too small (16 m²)


def test_the_surroundings_give_the_trees_on_the_ground_within_the_range_and_to_the_files():
    terrain = {"min": -100.0, "step": 50.0, "n": 5, "z": [float(j) for j in range(5) for _ in range(5)]}  # rises 1 m every 50 m north
    out = context3d.trees_on([ROAD, WALK], [], terrain, 50)
    assert out["rule"] == street_trees.RULE and out["height"] == street_trees.HEIGHT
    assert all(abs(x) <= 50 for x, _, _ in out["points"])  # cut to the range
    x, y, z = out["points"][0]
    assert z == pytest.approx((y + 100) / 50, abs=0.01)  # on the ground under it
    assert context3d.trees_on([WALK], [], terrain, 50) is None

    layers = {layer["short"]: layer for layer in context3d.export_layers({"trees": out})}
    crowns = layers["가로수(표현용)"]["curves"]
    assert len(crowns) == len(out["points"]) and all(c["closed"] for c in crowns)
    (cx, cy, cz), first = out["points"][0], crowns[0]["points"][0]
    assert math.hypot(first[0] - cx, first[1] - cy) == pytest.approx(street_trees.CROWN / 2, abs=0.01)
    assert first[2] == cz
