"""JSON adapters for signing in with ChatGPT; the work lives in chatgpt_auth.py.

The browser comes back to /auth/callback, an HTML page in webapp.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from sida import chatgpt_auth


class LoginStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_account: bool = False


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/settings/chatgpt")

    @router.get("")
    def get_status() -> dict:
        return core(chatgpt_auth.status)

    @router.post("/login")
    def post_login(request: Request, body: LoginStart | None = None) -> dict:
        # The callback comes back to this server on the port the screen is using.
        port = request.url.port or 80
        new_account = bool(body and body.new_account)
        return core(chatgpt_auth.start_login, port, new_account=new_account)

    @router.get("/models")
    def get_models() -> dict:
        return {"models": core(chatgpt_auth.list_models)}

    @router.delete("")
    def delete_login() -> dict:
        return core(chatgpt_auth.sign_out)

    return router
