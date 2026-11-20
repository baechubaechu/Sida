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
