"""JSON adapters for the web settings screen; the work lives in settings.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from sida import relay_key, settings


class SettingsChange(BaseModel):
    """Only the fields given are changed; the rest stay as they are."""

    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    local_profile: str | None = None
    conductor_provider: str | None = None
    worker_provider: str | None = None
    chatgpt_model: str | None = None
    worker_chatgpt_model: str | None = None
    rag_enabled: bool | None = None
    state_update: str | None = None
    telemetry_enabled: bool | None = None
    telemetry_share_inputs: bool | None = None


class KeyValue(BaseModel):
    value: str


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    contact: str = ""


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/settings")

    def call(fn, *args, **kwargs):
        try:
            return core(fn, *args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=f"unknown key: {exc.args[0]}") from exc
        except relay_key.RelayBusy as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except relay_key.RelayUnreachable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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

    # Asking the Sida relay for an access key (sida/relay_key.py). GET asks the relay whether the
    # waiting request was answered and saves the key when it was approved.
    @router.get("/relay-key")
    def check_relay_key() -> dict:
        return call(relay_key.check)

    @router.post("/relay-key")
    def ask_relay_key(body: KeyRequest) -> dict:
        return call(relay_key.ask, body.name, body.contact)

    @router.delete("/relay-key")
    def cancel_relay_key() -> dict:
        return call(relay_key.cancel)

    return router
