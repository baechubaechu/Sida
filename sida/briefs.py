#!/usr/bin/env python3
"""Brief (brief.md) fields and the markdown built from them."""

from __future__ import annotations

# The brief fields a new project can be created with, in brief.md order.
BRIEF_FIELD_KEYS: tuple[str, ...] = (
    "type", "site", "problem", "issues", "intention", "direction", "driver",
)

DRIVER_ALIASES = {
    "site": "site", "사이트": "site", "대지": "site",
    "idea": "idea", "아이디어": "idea", "개념": "idea", "concept": "idea",
    "program": "program", "프로그램": "program",
    "regulation": "regulation", "법규": "regulation", "code": "regulation", "규제": "regulation",
    "competition": "competition", "공모": "competition", "review": "competition", "발표": "competition",
}


def normalize_driver(raw: str) -> str:
    """Map free text to one of site | idea | program | regulation | competition (or keep raw)."""
    key = raw.strip().lower()
    return DRIVER_ALIASES.get(key, raw.strip())


def _issues_to_bullets(raw: str) -> str:
    items = [p.strip() for p in raw.split(",") if p.strip()]
    return "\n".join(f"- {item}" for item in items) if items else "-"


def build_brief_markdown(fields: dict[str, str]) -> str:
    def val(key: str) -> str:
        text = fields.get(key, "").strip()
        return text if text else "-"

    return f"""# Project Brief

## Project Type
{val("type")}

## Site
{val("site")}

## Core Problem
{val("problem")}

## Site Issues
{_issues_to_bullets(fields.get("issues", ""))}

## Design Intention
{val("intention")}

## Current Design Direction
{val("direction")}

## Primary Driver
{normalize_driver(fields.get("driver", "")) or "-"}
"""
