"""JSON adapters for sharing a project (공유); the work lives in share.py (docs/share.md)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sida import share, workspace


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photos: bool = True
    by: str = Field(default="", max_length=share.MAX_BY)


class ChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comments_open: bool | None = None
    new_links: bool = False


class ReplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=share.MAX_REPLY)


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved: bool


class SeenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(max_length=1000)


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/share")

    def call(fn, *args, **kwargs):
        try:
            return core(fn, *args, **kwargs)
        except share.ShareError as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message}) from exc

    def project(name: str):
        return workspace.find_project(load_config(), name).resolve()

    @router.get("")
    def get_share(name: str) -> dict:
        return call(share.plan, project(name))

    @router.post("")
    def publish(name: str, body: PublishBody) -> dict:
        return call(share.publish, project(name), photos=body.photos, by=body.by)

    @router.patch("")
    def change(name: str, body: ChangeBody) -> dict:
        return call(share.change, project(name), comments_open=body.comments_open, new_links=body.new_links)

    @router.delete("")
    def stop(name: str) -> dict:
        return call(share.stop, project(name))

    @router.get("/comments")
    def comments(name: str, refresh: bool = True) -> dict:
        path = project(name)
        if not refresh:
            return call(share.cached_comments, path)
        try:
            return call(share.refresh_comments, path)
        except HTTPException as exc:
            # The server out of reach: the comments kept here, with why they may be old.
            kept = share.cached_comments(path)
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            return {**kept, "stale": detail.get("message", "")}

    @router.post("/comments")
    def reply(name: str, body: ReplyBody) -> dict:
        return call(share.reply, project(name), body.parent, body.text)

    @router.patch("/comments/{comment_id}")
    def resolve(name: str, comment_id: str, body: ResolveBody) -> dict:
        return call(share.resolve, project(name), comment_id, body.resolved)

    @router.delete("/comments/{comment_id}")
    def delete_comment(name: str, comment_id: str) -> dict:
        return call(share.delete_comment, project(name), comment_id)

    @router.put("/comments/seen")
    def seen(name: str, body: SeenBody) -> dict:
        return call(share.mark_seen, project(name), body.ids)

    return router
