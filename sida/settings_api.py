"""JSON adapters for the web settings screen; the work lives in settings.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from sida import settings


class SettingsChange(BaseModel):
    """Only the fields given are changed; the rest stay as they are."""

    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    local_profile: str | None = None
    conductor_provider: str | None = None
    worker_provider: str | None = None
    rag_enabled: bool | None = None
    state_update: str | None = None


class KeyValue(BaseModel):
    value: str


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/settings")

    def call(fn, *args, **kwargs):
        try:
            return core(fn, *args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=f"unknown key: {exc.args[0]}") from exc

    @router.get("")
    def get_settings() -> dict:
        return call(settings.settings_view, load_config())

    @router.put("")
    def put_settings(body: SettingsChange) -> dict:
        call(settings.update_settings, load_config(), body.model_dump(exclude_none=True))
        return call(settings.settings_view, load_config())

    @router.put("/keys/{key_id}")
    def put_key(key_id: str, body: KeyValue) -> dict:
        return call(settings.set_key, key_id, body.value)

    return router
