"""How the 자동 조경 plugs into the core (see sida/experts/__init__.py)."""

from __future__ import annotations


def conductor_site(project_dir) -> str:
    """The landscape plan the designer last looked at, in one line ("" for none)."""
    try:
        from sida.experts.landscape import landscape

        return landscape.conductor_line(project_dir)
    except Exception:  # never stop a message
        return ""


def board_export_layers(project_dir) -> list[dict]:
    """The landscape plan shown, for the CAD/Rhino export (export.py)."""
    try:
        from sida.experts.landscape import export

        return export.layers(project_dir)
    except Exception:  # an export must not fail for the landscape
        return []


def api_router(load_config, core):
    from sida.experts.landscape.api import create_router

    return create_router(load_config, core)


PROPOSE = "propose_landscape"


def conductor_tools(project_dir) -> list[dict]:
    """`propose_landscape` once the site is looked up (the layout needs its lot)."""
    from sida.experts.site import site_facts

    if not site_facts.load_facts(project_dir):
        return []
    from sida.experts.landscape import generator

    return [{
        "name": PROPOSE,
        "description": (
            "Propose a landscape (조경) layout for the site when the designer asks to change or compare "
            "the landscape in words (a bigger plaza, more trees, narrower paths, no shrub band...). You "
            "only pick a style and turn its knobs; Sida lays it out by rule around the masses, checks it "
            "against the ordinance (조경면적, 교목 count) and shows it on the 자동 조경 card beside the "
            "three styles, where the designer compares it and places it if they like it. You get its "
            "figures back, and those of the plan placed on the table. Never state areas or tree counts "
            "of your own; use the figures you get."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "style": {"type": "string", "enum": list(generator.STYLES),
                          "description": "formal (axis, rows of trees), natural (curved paths, groups of trees), plaza (paved road side, planters)."},
                "plaza": {"type": "string", "enum": list(generator.PLAZA_SIZES),
                          "description": "Plaza size against the style's own; never below the 공개 공지 the rules ask. Leave out for normal."},
                "trees": {"type": "string", "enum": list(generator.TREE_COUNTS),
                          "description": "Trees: law (the 조경기준 count), more (+25%), most (+50%), room (as many as fit). Leave out for law."},
                "path": {"type": "number", "minimum": generator.PATH_RANGE[0], "maximum": generator.PATH_RANGE[1],
                         "description": "Path width in m. Leave out for the style's own."},
                "hedge": {"type": "number", "minimum": 0, "maximum": generator.HEDGE_RANGE[1],
                          "description": f"Shrub band width along the neighbours in m: 0 for none, else {generator.HEDGE_RANGE[0]:g}–{generator.HEDGE_RANGE[1]:g}. Leave out for 1.5."},
                "title": {"type": "string", "description": "Short name in the designer's language; leave out to have one made."},
                "reason": {"type": "string", "description": "One line: what the designer asked for."},
            },
            "required": ["style", "reason"],
            "additionalProperties": False,
        },
    }]


def conductor_call(project_dir, name: str, arguments: dict) -> dict:
    from sida.experts.landscape import landscape

    if name != PROPOSE:
        raise ValueError("unknown_tool")
    try:
        made = landscape.propose(project_dir, arguments)
    except LookupError as exc:
        raise ValueError("the site has no lot to lay out yet") from exc
    except ValueError as exc:
        raise ValueError(f"bad {exc}" if str(exc) in ("style", "plaza", "trees", "path", "hedge", "tune") else str(exc)) from exc
    title = made["proposal"]["title"]
    return {"result": made["text"], "notice": f"조경 제안 '{title}'을(를) 자동 조경 카드에 놓았습니다.", "open": "landscape"}
