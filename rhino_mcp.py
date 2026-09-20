#!/usr/bin/env python3
"""Rhino MCP bridge for Sida modeling mode."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp_stdio import McpError, McpStdioClient, iter_default_rhino_commands

# Tools the modeler may invoke automatically (no interactive ask_user / slot kill).
SAFE_TOOLS = frozenset(
    {
        "list_slots",
        "spawn_slot",
        "get_context",
        "list_objects",
        "get_selection",
        "set_selection",
        "run_python",
        "run_command",
        "run_csharp",
        "set_camera",
        "zoom_to_object",
        "zoom_to_layer",
        "open_doc",
        "save_doc",
        "get_commands",
        "g1_start",
        "g1_search_components",
        "g1_describe_component",
        "g1_place_component",
        "g1_place_slider",
        "g1_connect",
        "g1_connect_many",
        "g1_apply_graph",
        "g1_solve_graph",
        "g1_get_canvas_graph",
        "set_layer_material",
    }
)


def resolve_mcp_command(config: dict | None = None) -> list[str] | None:
    """Return argv for the Rhino MCP router, or None if not found."""
    modeling = (config or {}).get("modeling") or {}
    raw = modeling.get("mcp_command") or os.environ.get("SIDA_RHINO_MCP") or ""
    if isinstance(raw, list) and raw:
        return [str(x) for x in raw]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    for candidate in iter_default_rhino_commands():
        path = Path(candidate[0])
        if path.is_file():
            return candidate
    return None


class RhinoMcp:
    """Thin wrapper: open router, call safe tools, close."""

    def __init__(self, command: list[str], *, timeout: float = 90.0):
        self.client = McpStdioClient(command, timeout=timeout)
        self.slot: str | None = None

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> RhinoMcp:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        tool = str(tool or "").strip()
        if tool not in SAFE_TOOLS:
            raise McpError(f"tool not allowed in modeler: {tool}")
        payload = dict(args or {})
        if self.slot and "slot" not in payload:
            payload["slot"] = self.slot
        result = self.client.call_tool(tool, payload)
        if tool == "spawn_slot":
            self.slot = _extract_slot(result) or self.slot
        return result


def _extract_slot(result: Any) -> str | None:
    if isinstance(result, dict):
        for key in ("slot", "id", "slotId", "Slot"):
            if result.get(key):
                return str(result[key])
        payload = result.get("payload")
        if isinstance(payload, dict):
            for key in ("slot", "id", "slotId"):
                if payload.get(key):
                    return str(payload[key])
        if isinstance(payload, str) and payload.strip():
            return payload.strip()
    if isinstance(result, str) and result.strip():
        return result.strip()
    return None


def open_rhino_mcp(config: dict) -> RhinoMcp:
    cmd = resolve_mcp_command(config)
    if not cmd:
        raise McpError(
            "Rhino MCP router not found. Install Rhino-MCP-Platform, or set "
            "modeling.mcp_command / SIDA_RHINO_MCP to rhino-mcp-router.exe"
        )
    timeout = float((config.get("modeling") or {}).get("mcp_timeout") or 90)
    return RhinoMcp(cmd, timeout=timeout)
