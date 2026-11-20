"""자동 조경 for a project: the site, a mass scheme and the region the designer picked, laid out in
the three styles of generator.py and checked against what the rules ask (rules.py).

What the designer picks is kept in the project's `landscape.json` (`load_settings`): the mass scheme
the buildings come from (none: the first on the table), the region (a ring on the table; none: the
whole lot outside the buildings), the style shown, a seed (다시 섞기), the knobs (`tune`,
generator.Tune: plaza size, trees, path and shrub band width, for all three styles), the building's use
(for 공개 공지) and whether the plan shown is placed on the table (`placed`: drawn in the 3D view with
the tool closed, told to the Conductor and written in the CAD/Rhino export). The lot edges that face a
road are asked of the 연속지적 map once per site and kept there too. `summary` is a line for the
Conductor about the style shown.

`proposals` are layouts the Conductor proposed when the designer asked in words ("광장 넓히고 나무
더"): a style with its knobs, laid out and checked by rule like the three (the Conductor never places
a tree or sets an area). The card shows them beside the three; placing one copies its style, knobs and
seed into the settings. The last MAX_PROPOSALS are kept.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from sida import board
from sida.board_export import block_outline
from sida.experts.landscape import generator, rules
from sida.experts.site import landapi, site_facts
from sida.storage import atomic_write_text

SETTINGS_FILE = "landscape.json"
MAX_REGION_M2 = 30_000.0  # a region beyond this is not a site's yard (and would be slow)
MAX_RING = 200  # points of a drawn region
SEED_RANGE = (1, 9999)
SHOWN_SETTINGS = ("mass", "region", "style", "seed", "tune", "use", "placed")  # what the API gives back
MAX_PROPOSALS = 3
STYLE_WORDS = {"formal": "정형", "natural": "자연형", "plaza": "광장형"}


def _defaults() -> dict:
    return {"mass": None, "region": None, "style": "formal", "seed": 1, "tune": generator.Tune().as_dict(), "use": None,
            "placed": False, "proposals": []}


def _proposal(raw) -> dict | None:
    """A kept proposal as it was written, or None when it cannot be read."""
    if not isinstance(raw, dict) or raw.get("style") not in generator.STYLES:
        return None
    try:
        tune = generator.Tune.read(raw.get("tune"))
    except ValueError:
        return None
    seed = raw.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not SEED_RANGE[0] <= seed <= SEED_RANGE[1]:
        return None
    if not isinstance(raw.get("id"), str) or not raw["id"]:
        return None
    return {"id": raw["id"], "title": str(raw.get("title") or "")[:80], "style": raw["style"], "tune": tune.as_dict(),
            "seed": seed, "reason": str(raw.get("reason") or "")[:300], "at": str(raw.get("at") or ""),
            "by": str(raw.get("by") or "")[:40]}


def proposal_title(style: str, tune: generator.Tune) -> str:
    """"정형 · 광장 넓게 · 나무 50% 더"."""
    return " · ".join([STYLE_WORDS[style], *tune.words()])


def _ring(raw) -> list[list[float]] | None:
    if not isinstance(raw, list) or not 3 <= len(raw) <= MAX_RING:
        return None
    out = []
    for p in raw:
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)):
            return None
        if not all(abs(v) <= 5000 for v in p):
            return None
        out.append([round(float(p[0]), 2), round(float(p[1]), 2)])
    poly = Polygon(out).buffer(0)
    return out if poly.area >= 4 else None


def load_settings(project_dir) -> dict:
    """What the designer picked (module docstring), with the kept road edges under "roads" and the
    Conductor's line under "summary"; what cannot be read is left at its default."""
    try:
        data = json.loads((Path(project_dir) / SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = _defaults()
    if isinstance(data.get("mass"), str) and 0 < len(data["mass"]) <= 80:
        out["mass"] = data["mass"]
    out["region"] = _ring(data.get("region"))
    if data.get("style") in generator.STYLES:
        out["style"] = data["style"]
    seed = data.get("seed")
    if isinstance(seed, int) and not isinstance(seed, bool) and SEED_RANGE[0] <= seed <= SEED_RANGE[1]:
        out["seed"] = seed
    try:
        out["tune"] = generator.Tune.read(data.get("tune")).as_dict()
    except ValueError:
        pass
    if isinstance(data.get("proposals"), list):
        out["proposals"] = [p for p in map(_proposal, data["proposals"]) if p is not None][-MAX_PROPOSALS:]
    if isinstance(data.get("use"), str) and data["use"] in rules.load_rules()["open_space"]["uses"] or data.get("use") == "other":
        out["use"] = data["use"]
    out["placed"] = data.get("placed") is True
    if isinstance(data.get("proposal_count"), int) and not isinstance(data["proposal_count"], bool):
        out["proposal_count"] = data["proposal_count"]  # ids are never given twice
    if isinstance(data.get("roads"), dict):
        out["roads"] = data["roads"]
    if isinstance(data.get("summary"), str):
        out["summary"] = data["summary"]
    return out


def _write(project_dir, settings: dict) -> None:
    atomic_write_text(Path(project_dir) / SETTINGS_FILE, json.dumps(settings, ensure_ascii=False, indent=1) + "\n")


def save_settings(project_dir, changes: dict) -> dict:
    """Set what the designer picked: `mass` (a paper id or None), `region` (a ring of [x, y] in the
    table's metres, 3–200 points, or None for the whole lot), `style`, `seed`, `tune` (generator.Tune
    as a dict: the knobs left out go back to their defaults), `use` (a 공개 공지 use key, "other" or
    None), `placed` (bool). ValueError naming the key (or the knob) for a bad value. Returns the
    settings."""
    settings = load_settings(project_dir)
    if "mass" in changes:
        value = changes["mass"]
        if value is not None and not (isinstance(value, str) and 0 < len(value) <= 80):
            raise ValueError("mass")
        settings["mass"] = value
    if "region" in changes:
        value = changes["region"]
        if value is not None:
            value = _ring(value)
            if value is None:
                raise ValueError("region")
        settings["region"] = value
    if "style" in changes:
        if changes["style"] not in generator.STYLES:
            raise ValueError("style")
        settings["style"] = changes["style"]
    if "seed" in changes:
        value = changes["seed"]
        if not (isinstance(value, int) and not isinstance(value, bool) and SEED_RANGE[0] <= value <= SEED_RANGE[1]):
            raise ValueError("seed")
        settings["seed"] = value
    if "tune" in changes:
        settings["tune"] = generator.Tune.read(changes["tune"]).as_dict()
    if "use" in changes:
        value = changes["use"]
        if value is not None and value != "other" and value not in rules.load_rules()["open_space"]["uses"]:
            raise ValueError("use")
        settings["use"] = value
    if "placed" in changes:
        if not isinstance(changes["placed"], bool):
            raise ValueError("placed")
        settings["placed"] = changes["placed"]
    _write(project_dir, settings)
    return settings


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------


def _lot(plan: dict):
    return unary_union([Polygon(r) for p in plan["parcels"] for r in p["rings"] if len(r) >= 3]).buffer(0)


def _scheme(project_dir, mass_id: str | None) -> dict | None:
    papers = [p for p in board.load_board(Path(project_dir))["papers"] if p.get("kind") == "mass" and p.get("blocks")]
    if mass_id:
        return next((p for p in papers if p["id"] == mass_id), None)
    return papers[0] if papers else None


def buildings_of(scheme: dict | None, frame: dict | None) -> list[tuple[Polygon, float]]:
    """The scheme's blocks as footprints on the table with their heights (m)."""
    if not scheme:
        return []
    height = scheme.get("floor_height") or board.DEFAULT_FLOOR_HEIGHT
    return [(Polygon(block_outline(frame, b)).buffer(0), b["floors"] * height) for b in scheme["blocks"]]


def road_edges(project_dir, plan: dict, facts: dict, lot, *, http_get=None, kept_only: bool = False) -> tuple[list[dict], str]:
    """The lot edges that face a road ({"line", "width"}) and "" — or [] and why they are not known.
    Asked of the 연속지적 map once per site and kept in landscape.json (`kept_only`: never ask)."""
    from sida.experts.site import envelope, setbacks

    key = ",".join(sorted(p["pnu"] for p in facts["parcels"]))
    data = load_settings(project_dir)
    kept = data.get("roads") or {}
    if kept.get("key") == key and isinstance(kept.get("lines"), list):
        return [{"line": LineString(r["line"]), "width": r.get("width")} for r in kept["lines"] if len(r.get("line") or []) >= 2], ""
    if kept_only:
        return [], ""
    try:
        parcels = envelope.neighbours(plan, {p["pnu"] for p in facts["parcels"]}, http_get=http_get)
    except landapi.LandApiError:
        return [], "도로 위치를 지적도에서 받지 못해 대지의 가장 긴 변을 도로로 봄"
    runs = setbacks.edges(lot, parcels)["runs"]
    out = []
    for run in runs:
        if run["kind"] != "road":
            continue
        for part in run["line"].geoms:
            out.append({"line": part, "width": run["width"]})
    merged = [{"line": [[round(x, 2), round(y, 2)] for x, y in r["line"].coords], "width": r["width"]} for r in out]
    data["roads"] = {"key": key, "lines": merged}
    _write(project_dir, data)
    return out, ""


def _longest_edge(lot) -> list[dict]:
    poly = max(getattr(lot, "geoms", [lot]), key=lambda p: p.area)
    pts = list(poly.exterior.coords)
    a, b = max(zip(pts, pts[1:], strict=False), key=lambda ab: LineString(ab).length)
    return [{"line": LineString([a, b]), "width": None}]


# ---------------------------------------------------------------------------
# the plans
# ---------------------------------------------------------------------------


def _check(id_: str, title: str, value: str, need: str, ok, detail: str = "", quote: str = "", source: str = "") -> dict:
    return {"id": id_, "title": title, "value": value, "need": need, "ok": ok, "detail": detail, "quote": quote, "source": source}


def _m2(v: float) -> str:
    return f"{v:,.1f}㎡" if v < 100 else f"{v:,.0f}㎡"


def checks(plan: dict, need: dict) -> list[dict]:
    """How a plan stands against what the rules ask: [{"id", "title", "value", "need", "ok": True |
    False | None (nothing to hold it to), "detail", "quote", "source"}]."""
    land, plant, open_ = need["landscape"], need["planting"], need["open_space"]
    out = []
    asked = land["area_m2"]
    out.append(_check("landscape", "조경면적", _m2(plan["planting_m2"]), f"{_m2(asked)} 이상" if asked else "-",
                      plan["planting_m2"] + 1e-6 >= asked if asked else None,
                      (land["detail"] + ". 잔디·지피·관목 띠·식재함만 셈(포장·광장 제외)") if asked else land["detail"],
                      land["quote"], land["source"]))
    trees = plant["trees"]
    out.append(_check("trees", "교목", f"{plan['trees_in_lot']}주", f"{trees}주 이상" if trees else "-",
                      plan["trees_in_lot"] >= trees if trees else None,
                      plant["detail"] + ". 나무마다 1주로 셈(큰 나무는 2·4·8주로 셀 수 있음)", plant["quote"], plant["source"]))
    if plant["shrubs"]:
        out.append(_check("shrubs", "관목", f"띠 {_m2(plan['areas']['hedge'])}", f"{plant['shrubs']}주 이상", None,
                          "관목 수는 수종을 정할 때 셈. 띠와 식재함, 잔디 가장자리에 나눠 심음", plant["quote"], plant["source"]))
    if open_["status"] == "read":
        ok = plan["plaza_m2"] + 1e-6 >= open_["area_m2"]
        width = plan.get("plaza_width_ok")
        detail = open_["detail"]
        if width is False:
            detail += f". 광장 폭이 {open_['least_width_m']:g}m에 못 미치는 곳이 있음"
        out.append(_check("open_space", "공개 공지", f"광장 {_m2(plan['plaza_m2'])}", f"{_m2(open_['area_m2'])} 이상",
                          ok and width is not False, detail, open_["quote"], open_["source"]))
    elif open_["status"] in ("conditional", "check"):
        out.append(_check("open_space", "공개 공지", f"광장 {_m2(plan['plaza_m2'])}", "-", None, open_["detail"], open_["quote"], open_["source"]))
    return out


def summary_line(plan: dict, need: dict) -> str:
    """One English line for the Conductor about the plan shown."""
    land = need["landscape"]["area_m2"]
    trees = need["planting"]["trees"]
    knobs = generator.Tune.read(plan.get("tune")).words()
    shown = plan["style"] + (" with " + ", ".join(knobs) if knobs else "")
    parts = [f"Landscape plan on the drafting table ({shown}, rule-generated): planting {plan['planting_m2']:.0f} m2"
             + (f" (ordinance asks {land:.0f} m2)" if land else ""),
             f"{plan['trees_in_lot']} trees" + (f" (asks {trees})" if trees else ""),
             f"paved plaza {plan['plaza_m2']:.0f} m2"]
    return ", ".join(parts) + "."


def _site(project_dir: Path) -> tuple[dict, dict, object]:
    """The site facts, the lot's plan on the table and the lot as a shape. LookupError("no_site" |
    "no_plan") without a site or its boundaries."""
    facts = site_facts.load_facts(project_dir)
    if not facts or not facts["summary"]["zoning"]:
        raise LookupError("no_site")
    plan = board.site_plan(facts["parcels"])
    if plan is None:
        raise LookupError("no_plan")
    return facts, plan, _lot(plan)


def _region(drawn, lot, buildings):
    """The ground to lay out: the ring drawn (or the lot), kept to the lot, without the buildings.
    ValueError("region" | "region_too_big")."""
    taken = unary_union([b for b, _ in buildings]) if buildings else Polygon()
    region = (Polygon(drawn).buffer(0).intersection(lot) if drawn else lot).difference(taken)  # the lot's only
    if region.is_empty or region.area < 4:
        raise ValueError("region")
    if region.area > MAX_REGION_M2:
        raise ValueError("region_too_big")
    return region


def _lay_out(project_dir: Path, facts: dict, plan: dict, lot, region, buildings, gross, use, seed, styles, *,
             tune: generator.Tune | None = None, http_get=None, kept_only: bool = False, extra=()) -> dict:
    """The styles asked laid out in the region with the knobs and checked: {"need", "plans", "note",
    "municipality", "area", "extra"}; `extra` are more (style, Tune, seed) to lay out in the same
    region ("extra": their plans)."""
    roads, note = road_edges(project_dir, plan, facts, lot, http_get=http_get, kept_only=kept_only)
    if not roads:
        roads = _longest_edge(lot)
        note = note or "대지가 도로에 닿는 변을 찾지 못해 가장 긴 변을 도로로 봄"
    s = facts["summary"]
    zone = s["zoning"][0]["zone"] if len(s["zoning"]) == 1 else ""
    municipality = s.get("municipality") or ""
    area = s["total_area_m2"] if s.get("area_complete") else None
    need = rules.requirement(zone, municipality, area, gross, use)
    open_ = need["open_space"]
    inputs = generator.Inputs(
        region=region, lot=lot, buildings=buildings, roads=roads, latitude=plan["origin"]["lat"],
        open_space_m2=open_["area_m2"] if open_["status"] == "read" else None,
        open_space_width=open_.get("least_width_m") if open_["status"] == "read" else None,
        trees_needed=need["planting"]["trees"], seed=seed)
    def one(style, knobs, at_seed):
        inputs.seed = at_seed
        laid = generator.generate(inputs, style, knobs)
        laid["checks"] = checks(laid, need)
        return laid

    made = [one(style, tune, seed) for style in styles]
    more = [one(style, knobs, at_seed) for style, knobs, at_seed in extra]
    return {"need": need, "plans": made, "note": note, "municipality": municipality, "area": area, "extra": more}


def _table(project_dir: Path) -> dict:
    """What a layout on the table starts from: the site, the settings, the masses and the region."""
    facts, plan, lot = _site(project_dir)
    settings = load_settings(project_dir)
    scheme = _scheme(project_dir, settings["mass"])
    buildings = buildings_of(scheme, plan.get("frame"))
    return {"facts": facts, "plan": plan, "lot": lot, "settings": settings, "scheme": scheme, "buildings": buildings,
            "gross": board.blocks_areas(scheme["blocks"])[1] if scheme else None,
            "region": _region(settings["region"], lot, buildings)}


def plans(project_dir, *, http_get=None, kept_only: bool = False, proposals: bool = True) -> dict:
    """
    The three layouts for the project as it stands, with the knobs: {"settings", "uses", "masses":
    [{"id", "title"}], "mass": the scheme used or None, "gross_m2", "site_area_m2", "region": [{"outer",
    "holes"}], "region_drawn", "roads_note", "requirement" (rules.requirement), "plans":
    [generator.generate + "checks"], "proposals": [{"id", "title", "style", "tune", "seed", "reason",
    "at", "plan"}] (the Conductor's, laid out the same way; [] when `proposals` is off)}.
    LookupError("no_site" | "no_plan") without a site or its boundaries; ValueError ("region") when the
    region leaves nothing to lay out or is too big. `kept_only`: use only the road edges already kept
    (no map is asked; the export and the Conductor must be quick).
    """
    project_dir = Path(project_dir)
    t = _table(project_dir)
    settings = t["settings"]
    kept = settings["proposals"] if proposals else []
    laid = _lay_out(project_dir, t["facts"], t["plan"], t["lot"], t["region"], t["buildings"], t["gross"], settings["use"],
                    settings["seed"], generator.STYLES, tune=generator.Tune.read(settings["tune"]), http_get=http_get,
                    kept_only=kept_only,
                    extra=[(k["style"], generator.Tune.read(k["tune"]), k["seed"]) for k in kept])
    need, made = laid["need"], laid["plans"]
    shown = next(p for p in made if p["style"] == settings["style"])
    line = summary_line(shown, need)
    if settings.get("summary") != line:
        data = load_settings(project_dir)
        data["summary"] = line
        _write(project_dir, data)
    all_masses = [p for p in board.load_board(project_dir)["papers"] if p.get("kind") == "mass" and p.get("blocks")]
    return {
        "settings": {k: settings[k] for k in SHOWN_SETTINGS},
        "uses": rules.uses(laid["municipality"]),
        "masses": [{"id": p["id"], "title": p.get("title") or ""} for p in all_masses],
        "mass": t["scheme"]["id"] if t["scheme"] else None,
        "gross_m2": round(t["gross"], 1) if t["gross"] is not None else None,
        "site_area_m2": laid["area"],
        "region": generator._rings(t["region"]),
        "region_drawn": bool(settings["region"]),
        "roads_note": laid["note"],
        "requirement": need,
        "plans": made,
        "proposals": [{**k, "plan": plan} for k, plan in zip(kept, laid["extra"], strict=True)],
    }


# ---------------------------------------------------------------------------
# the Conductor's proposals
# ---------------------------------------------------------------------------


def _figures(plan: dict) -> str:
    """"planting 580 m2 (ok, asks 152), 24 trees (ok, asks 16), plaza 128 m2"."""
    out = []
    for c in plan["checks"]:
        state = {True: "meets", False: "SHORT of", None: "for reference"}[c["ok"]]
        need = f", {state} {c['need']}" if c["need"] and c["need"] != "-" else ""
        out.append(f"{c['title']} {c['value']}{need}")
    return "; ".join(out)


def propose(project_dir, raw: dict, *, by: str = "conductor") -> dict:
    """
    Keep a layout the Conductor proposed: `raw` {"style", "plaza", "trees", "path", "hedge" (the
    knobs, generator.Tune; left out: the default), "title" (optional), "reason"}. It is laid out and
    checked now (the road edges already kept, no map is asked), so a proposal that cannot be laid out
    is refused (ValueError naming why, or LookupError without a site). Returns {"proposal", "plan",
    "placed": the plan placed on the table or None, "text": the figures for the Conductor}.
    """
    project_dir = Path(project_dir)
    if not isinstance(raw, dict) or raw.get("style") not in generator.STYLES:
        raise ValueError("style")
    tune = generator.Tune.read({k: raw[k] for k in ("plaza", "trees", "path", "hedge") if raw.get(k) is not None})
    t = _table(project_dir)
    settings = t["settings"]
    current = generator.Tune.read(settings["tune"])
    extra = [(raw["style"], tune, settings["seed"])]
    if settings["placed"]:
        extra.append((settings["style"], current, settings["seed"]))
    laid = _lay_out(project_dir, t["facts"], t["plan"], t["lot"], t["region"], t["buildings"], t["gross"], settings["use"],
                    settings["seed"], [], kept_only=True, extra=extra)
    plan = laid["extra"][0]
    placed = laid["extra"][1] if settings["placed"] else None
    title = str(raw.get("title") or "").strip()[:80] or proposal_title(raw["style"], tune)
    data = load_settings(project_dir)
    n = max([data.get("proposal_count", 0)] + [int(p["id"][1:]) for p in data["proposals"] if p["id"][1:].isdigit()]) + 1
    data["proposal_count"] = n
    proposal = {"id": f"p{n}", "title": title, "style": raw["style"], "tune": tune.as_dict(), "seed": settings["seed"],
                "reason": str(raw.get("reason") or "").strip()[:300], "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by}
    data["proposals"] = [*data["proposals"], proposal][-MAX_PROPOSALS:]
    _write(project_dir, data)
    text = f"Landscape proposal {proposal['id']} \"{title}\" ({raw['style']}" + (
        ", " + ", ".join(tune.words()) if tune.words() else "") + f"): {_figures(plan)}."
    if placed is not None:
        text += f" The plan now on the table ({proposal_title(settings['style'], current)}): {_figures(placed)}."
    else:
        text += " No landscape plan is placed on the table yet."
    return {"proposal": proposal, "plan": plan, "placed": placed, "text": text}


def drop_proposal(project_dir, proposal_id: str) -> bool:
    """Take a proposal away; False when there is none by that id."""
    data = load_settings(project_dir)
    kept = [p for p in data["proposals"] if p["id"] != proposal_id]
    if len(kept) == len(data["proposals"]):
        return False
    data["proposals"] = kept
    _write(project_dir, data)
    return True


# ---------------------------------------------------------------------------
# from Rhino
# ---------------------------------------------------------------------------


def _even_odd(rings):
    """A footprint's rings as one shape: a ring inside another is a hole (the snapshot's rule)."""
    shape = Polygon()
    for ring in rings:
        if len(ring) >= 3:
            shape = shape.symmetric_difference(Polygon(ring).buffer(0))
    return shape


def rhino_buildings(snapshot: dict) -> list[tuple[Polygon, float]]:
    """The building objects of a Rhino snapshot as footprints with their tops above the ground (m):
    the objects on layers whose meaning is a building, with a footprint and a height."""
    from sida.experts.rhino import snapshot as snap

    meaning = snap.meaning_of(snapshot)
    out = []
    for item in snapshot.get("objects") or []:
        if meaning.get(item.get("layer"), "") not in snap.BUILT or not item.get("footprint") or item.get("height") is None:
            continue
        shape = _even_odd(item["footprint"])
        if not shape.is_empty:
            out.append((shape, max((item.get("base") or 0.0) + item["height"], 0.1)))
    return out


def rhino_plan(project_dir, snapshot: dict, *, region=None, style: str | None = None, seed: int | None = None,
               tune: dict | None = None, use=..., http_get=None) -> dict:
    """
    One layout around the building objects of a Rhino snapshot, in the region the designer picked
    in Rhino (a ring in the snapshot's metres, kept to the lot; None: the whole lot): {"plan"
    (generator.generate + "checks"), "requirement", "roads_note", "gross_m2"}. The style, seed, knobs
    (`tune`, generator.Tune as a dict) and use default to the table's (landscape.json); nothing is kept.
    Errors as `plans`.
    """
    from sida.experts.rhino import snapshot as snap

    project_dir = Path(project_dir)
    facts, plan, lot = _site(project_dir)
    settings = load_settings(project_dir)
    style = style or settings["style"]
    if style not in generator.STYLES:
        raise ValueError("style")
    seed = settings["seed"] if seed is None else seed
    if isinstance(seed, bool) or not isinstance(seed, int) or not SEED_RANGE[0] <= seed <= SEED_RANGE[1]:
        raise ValueError("seed")
    knobs = generator.Tune.read(settings["tune"] if tune is None else tune)
    use = settings["use"] if use is ... else use
    if use is not None and use != "other" and use not in rules.load_rules()["open_space"]["uses"]:
        raise ValueError("use")
    drawn = None
    if region is not None:
        drawn = _ring(region)
        if drawn is None:
            raise ValueError("region")
    buildings = rhino_buildings(snapshot)
    area = facts["summary"]["total_area_m2"] if facts["summary"].get("area_complete") else None
    gross = snap.figures(snapshot, area).get("floor_area_m2") if buildings else None
    laid = _lay_out(project_dir, facts, plan, lot, _region(drawn, lot, buildings), buildings, gross, use, seed, [style],
                    tune=knobs, http_get=http_get)
    return {"plan": laid["plans"][0], "requirement": laid["need"], "roads_note": laid["note"],
            "gross_m2": round(gross, 1) if gross else None}


def conductor_line(project_dir) -> str:
    """The kept line about the plan placed on the table, for the Conductor ("" when none is)."""
    path = Path(project_dir) / SETTINGS_FILE
    if not path.exists():
        return ""
    settings = load_settings(project_dir)
    return settings.get("summary", "") if settings["placed"] else ""


def placed_plan(project_dir) -> dict | None:
    """The plan placed on the table, worked out again from what is kept (no map is asked), or None."""
    path = Path(project_dir) / SETTINGS_FILE
    if not path.exists() or not load_settings(project_dir)["placed"]:
        return None
    try:
        made = plans(project_dir, kept_only=True, proposals=False)
    except (LookupError, ValueError):
        return None
    return next((p for p in made["plans"] if p["style"] == made["settings"]["style"]), None)
