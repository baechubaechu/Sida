"""JSON adapters for document editing; the workflows live in editing.py and engine.py."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sida.editing import EditingService


class DocumentEdit(BaseModel):
    content: str
    expected_revision: str


class StateRequest(BaseModel):
    agent: str


def create_router(service: EditingService, load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}")

    def call(fn, *args, **kwargs):
        try:
            return core(fn, *args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="document not found") from exc

    @router.get("/documents/{kind}")
    def get_document(name: str, kind: str) -> dict:
        return asdict(call(service.read_document, load_config(), name, kind))

    @router.put("/documents/{kind}")
    def put_document(name: str, kind: str, body: DocumentEdit) -> dict:
        return asdict(call(
            service.save_document, load_config(), name, kind, body.content,
            expected_revision=body.expected_revision,
        ))

    @router.post("/state-proposals")
    def propose(name: str, body: StateRequest) -> dict:
        pending = call(service.propose_state, load_config(), name, body.agent)
        if pending is None:
            return {"proposal": None}
        return {"proposal": {
            "id": pending.id, "agent": pending.proposal.agent["id"],
            "diff": pending.proposal.diff,
        }}

    @router.post("/state-proposals/{proposal_id}/apply")
    def apply(name: str, proposal_id: str) -> dict:
        document = call(service.apply_state, load_config(), name, proposal_id)
        return {"applied": True, "document": asdict(document)}

    @router.post("/state-proposals/{proposal_id}/skip")
    def skip(name: str, proposal_id: str) -> dict:
        call(service.discard_state, load_config(), name, proposal_id)
        return {"skipped": True}

    return router
