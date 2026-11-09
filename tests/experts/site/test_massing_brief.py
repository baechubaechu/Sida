from __future__ import annotations

import math

from sida.experts.site import massing_brief


def _plan(angle_deg: float = 0.0) -> dict:
    """A 40 × 20 m lot around the origin, its long side along `angle_deg` from east."""
    a = math.radians(angle_deg)

    def at(u, v):
        return [round(u * math.cos(a) - v * math.sin(a), 4), round(u * math.sin(a) + v * math.cos(a), 4)]

    ring = [at(-20, -10), at(20, -10), at(20, 10), at(-20, 10)]
    return {"parcels": [{"rings": [ring]}], "frame": {"x": 0.0, "y": 0.0, "angle": a}, "origin": {"lon": 127.0, "lat": 37.5}}


def test_the_lot_is_given_in_the_frame_blocks_stand_in():
    lines = massing_brief.lot_lines(_plan(30))
    text = "\n".join(lines)
    # u along the long side, 30° from east, is bearing 60° from north (동쪽); v is 90° to its left.
    assert "bearing 60° from north, 동쪽" in text and "bearing 330°, 북쪽" in text
    assert "u -20.0 to 20.0 m, v -10.0 to 10.0 m (about 40.0 × 20.0 m)" in text
    assert "Lot outline (u, v): (-20, -10), (20, -10), (20, 10), (-20, 10)" in text
    assert "inside this outline" in lines[-1]
    assert massing_brief.lot_lines({"parcels": [], "frame": {"x": 0, "y": 0, "angle": 0}}) == []


def test_a_long_outline_is_thinned():
    plan = _plan()
    plan["parcels"][0]["rings"][0] = [[20 * math.cos(t / 50 * 2 * math.pi), 10 * math.sin(t / 50 * 2 * math.pi)] for t in range(50)]
    outline = next(line for line in massing_brief.lot_lines(plan) if line.startswith("Lot outline"))
    assert outline.count("(") - 1 == massing_brief.MAX_OUTLINE_POINTS


def _building(cx, cy, height, **extra):
    return {"outline": [[cx - 3, cy - 3], [cx + 3, cy - 3], [cx + 3, cy + 3], [cx - 3, cy + 3]], "height": height, **extra}


def test_the_surroundings_are_summed_up_side_by_side():
    around = {
        "buildings": [
            _building(0, 25, 30, floors=9, name="북쪽 빌딩", height_source="ledger"),  # 12 m from the lot's north edge
            _building(0, 45, 60, floors=18, height_source="estimate"),  # farther and taller
            _building(0, -30, 12),  # south
            _building(0, 200, 99),  # too far
            _building(0, 0, 40, on_site=True),
            _building(30, 0, 50, display_only=True),  # VWorld only: not sent
            _building(-30, 0, 50, height_source="api_estimate"),  # VWorld floors: not sent
        ],
        "areas": [{"kind": "road", "ring": [[-30, 12], [30, 12], [30, 20], [-30, 20]]}],
        # a 3 × 3 grid, 40 m apart, falling 2 m from west to east
        "terrain": {"min": -40, "step": 40, "n": 3, "z": [1, 0, -1] * 3},
    }
    text = "\n".join(massing_brief.around_lines(_plan(), around))
    assert "- 북쪽: 2 buildings; nearest 30 m 9층, 12 m away 북쪽 빌딩; tallest 60 m 18층 (추정 높이), 32 m away" in text
    assert "- 남쪽: 1 building; nearest 12 m, 17 m away" in text
    assert "- 동쪽: no building" in text and "- 서쪽: no building" in text  # the VWorld-only ones are left out
    assert "existing building(s), tallest 40 m" in text
    assert "- Road along the lot: 북쪽" in text
    assert "falls about 1.0 m across the lot, lowest toward 동쪽" in text
    assert "99 m" not in text


def test_the_conductor_waits_for_no_surroundings(tmp_path, monkeypatch):
    from sida.experts.site import context3d, context_range

    plan = _plan()
    context_range.save_shown(tmp_path, True)
    started = []
    monkeypatch.setattr(context3d, "cached", lambda *a, **k: None)
    monkeypatch.setattr(massing_brief, "_warm", lambda plan, picked: started.append(picked))
    lines = massing_brief.surroundings_lines(tmp_path, plan)
    assert "being prepared" in lines[0]
    monkeypatch.setattr(context3d, "cached", lambda *a, **k: {"buildings": [_building(0, 25, 30)]})
    assert "nearest 30 m" in "\n".join(massing_brief.surroundings_lines(tmp_path, plan))
    context_range.save_shown(tmp_path, False)
    assert massing_brief.surroundings_lines(tmp_path, plan) == []
