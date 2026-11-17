"""Sharing a project (공유): a snapshot on Sida's server that others open with a link and comment on.

The designer presses 공유 on the drafting table. The app makes a snapshot of the project as the
viewer page draws it and uploads it to the Sida data server (the relay, relay/shares.py) with
this person's Sida access key. The server gives two links: one to look and comment, one only to
look. Pressing it again uploads a new version (판) behind the same links. The comments people
leave come back here (`comments`) and show as pins on the table; the designer answers, marks
them resolved or deletes them from the table.

What goes up (2026-11-17 지훈):
- the papers on the table that are on shown layers: massing schemes (with their figures),
  tracings, notes, and photos shrunk to SHARE_PHOTO_EDGE px on the long side (or left out);
- the site card (area, zoning and rule lines) and the site's frame: where its middle is, the
  frame blocks stand in, the parcels' numbers and addresses;
- never: conversations with the Conductor or the experts (only the designer sees them), expert
  results, the Rhino model, sections, the AI section, the idea board, and no terrain, contours
  or surroundings (NGII rules). Parcel boundaries are VWorld's data, which may not be stored
  (이용약관 제19조): the viewer's page asks the server for them each time it opens.

The project keeps what it knows about its share in share.json: the server's share id, the
links, the newest version, and the comments last collected, which stay after the share is
turned off ("받아 둔 댓글은 내 Sida에 남습니다").
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from sida import board, relay, settings
from sida.project import section_body
from sida.storage import atomic_write_text

STATE_FILE = "share.json"
FORMAT = 1
SHARE_PHOTO_EDGE = 2000  # px, the long side of a shared photo
JPEG_QUALITY = 82
SHARED_KINDS = ("site", "mass", "tracing", "note", "photo")
LEFT_OUT_KINDS = ("expert", "rhino", "section")
MAX_BY = 40
MAX_REPLY = 1000
TIMEOUT = 60


class ShareError(Exception):
    """Sharing could not go ahead; `status` is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 400, code: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


# What a refusal of the server means for the designer (relay/shares.py LimitReached codes).
LIMIT_MESSAGES = {
    "share_bytes": "한 프로젝트의 공유는 {share_mb}MB까지입니다. 사진을 빼고 올려 보세요.",
    "owner_bytes": "내 공유를 모두 합쳐 {owner_mb}MB까지입니다. 다른 프로젝트의 공유를 꺼 주세요.",
    "owner_shares": "공유는 한 번에 {owner_shares}개까지입니다. 다른 프로젝트의 공유를 꺼 주세요.",
    "new_shares": "새 공유는 {period_days}일에 {new_shares}개까지입니다. 며칠 뒤 다시 해 주세요.",
    "uploads_per_day": "올리기는 하루 {uploads_per_day}번까지입니다. 내일 다시 올려 주세요.",
    "comments": "한 공유에 댓글이 너무 많습니다.",
}
LIMIT_DEFAULTS = {"share_mb": 20, "owner_mb": 100, "owner_shares": 10, "new_shares": 10, "period_days": 14,
                  "uploads_per_day": 20}


def _http(method: str, url: str, *, headers: dict, data: bytes | None = None,
          json_body: dict | None = None) -> tuple[int, dict]:
    """One call to the server: (status, JSON answer). Tests replace this."""
    try:
        r = requests.request(method, url, headers=headers, data=data, json=json_body, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ShareError("Sida 자료 서버에 닿지 못했습니다. 인터넷 연결을 확인해 주세요.", 502) from exc
    try:
        body = r.json()
    except ValueError:
        body = {}
    return r.status_code, body if isinstance(body, dict) else {}


def _server_url() -> str:
    """The Sida data server's address (settings, else the team's server); "" when not valid."""
    value = settings.read_key(relay.ENV_NAME).rstrip("/")
    if not value:
        return relay.DEFAULT_URL
    return value if relay.valid_url(value) else ""


def _key() -> str:
    value = settings.read_key(relay.TOKEN_ENV)
    return value if relay.valid_token(value) else ""


def _server() -> tuple[str, dict]:
    """The server's address and the access key header; ShareError without a key."""
    base, key = _server_url(), _key()
    if not key:
        raise ShareError("공유하려면 Sida 키가 필요합니다. 설정 창의 'Sida 키 받기'에서 받아 주세요.", 400, "no_key")
    if not base:
        raise ShareError("Sida 자료 서버 주소가 올바르지 않습니다. 설정 창에서 확인해 주세요.", 400, "no_server")
    return base, {"Authorization": f"Bearer {key}"}


def _call(method: str, path: str, *, data: bytes | None = None, json_body: dict | None = None,
          usage: dict | None = None) -> dict:
    base, headers = _server()
    if data is not None:
        headers = {**headers, "Content-Type": "application/zip"}
    status, body = _http(method, f"{base}{path}", headers=headers, data=data, json_body=json_body)
    if status < 400:
        return body
    detail = body.get("detail")
    if status == 429 and isinstance(detail, dict):
        limits = {**LIMIT_DEFAULTS, **((usage or {}).get("limits") or {})}
        code = str(detail.get("code") or "")
        message = LIMIT_MESSAGES.get(code, "서버의 공유 한도에 닿았습니다.").format(**limits)
        raise ShareError(message, 429, code)
    if status in (401, 403):
        raise ShareError("Sida 키를 서버가 받지 않았습니다. 설정 창에서 키를 확인해 주세요.", 403, "key_refused")
    if status == 404:
        raise ShareError("서버에 이 공유가 없습니다. 보관 기간이 지났거나 꺼졌을 수 있습니다.", 404, "gone")
    if status == 503:
        raise ShareError("Sida 자료 서버에 공유가 아직 준비되지 않았습니다.", 503, "not_ready")
    text = detail if isinstance(detail, str) else ""
    raise ShareError(f"서버가 받지 않았습니다. {text}".strip(), 400 if status == 400 else 502)


# ---------------------------------------------------------------------------
# What the project keeps
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state(project_path: Path) -> dict:
    try:
        data = json.loads((Path(project_path) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(project_path: Path, state: dict) -> dict:
    atomic_write_text(Path(project_path) / STATE_FILE, json.dumps(state, ensure_ascii=False, indent=1))
    return state


def _link(base: str, link: str) -> str:
    return f"{base}/s/{link}" if link else ""


def _from_server(state: dict, share: dict) -> dict:
    base = _server_url()
    versions = share.get("versions") or []
    return {
        **state,
        "id": share.get("id", state.get("id", "")),
        "on": True,
        "comment_url": _link(base, share.get("comment_link", "")),
        "view_url": _link(base, share.get("view_link", "")),
        "version": share.get("latest") or (versions[-1]["number"] if versions else 0),
        "versions": [{"number": v.get("number"), "created": v.get("created")} for v in versions],
        "bytes": share.get("bytes", 0),
        "expires": share.get("expires", ""),
        "comments_open": bool(share.get("comments_open", True)),
        "usage": share.get("usage") or state.get("usage") or {},
    }


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------


def _hidden_layers(layers: list[dict]) -> set[str]:
    """Layers turned off, with every layer under them."""
    off = {layer["id"] for layer in layers if not layer.get("visible", True)}
    changed = True
    while changed:
        changed = False
        for layer in layers:
            if layer["id"] not in off and layer.get("parent") in off:
                off.add(layer["id"])
                changed = True
    return off


def _layer_of(paper: dict) -> str:
    return paper.get("layer") or paper.get("kind", "")


def _shown(view: dict) -> tuple[list[dict], dict]:
    """The papers that go up, and how many of each kind were left out."""
    off = _hidden_layers(view.get("layers") or [])
    papers, left = [], {}
    for paper in view.get("papers") or []:
        kind = paper.get("kind")
        if _layer_of(paper) in off:
            continue
        if kind in LEFT_OUT_KINDS or kind not in SHARED_KINDS:
            left[kind] = left.get(kind, 0) + 1
            continue
        if kind == "photo" and str(paper.get("file", "")).endswith(".pdf"):
            left["pdf"] = left.get("pdf", 0) + 1
            continue
        if kind == "mass":  # blocks on hidden layers stay home
            blocks = [b for b in paper.get("blocks") or [] if b.get("layer", "") not in off]
            if not blocks:
                continue
            paper = {**paper, "blocks": blocks}
        papers.append(paper)
    return papers, left


def shrink_photo(data: bytes, edge: int = SHARE_PHOTO_EDGE) -> tuple[bytes, str]:
    """A photo for the web: at most `edge` px on its long side, as JPEG (PNG when it has
    transparency). Returns (bytes, extension). ValueError for a file that is not a picture."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("not a picture") from exc
    image.thumbnail((edge, edge))
    out = io.BytesIO()
    clear = image.mode in ("RGBA", "LA", "P") and "transparency" in image.info or image.mode in ("RGBA", "LA")
    if clear:
        image.save(out, "PNG", optimize=True)
        return out.getvalue(), "png"
    image.convert("RGB").save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue(), "jpg"


def _site(view: dict) -> dict | None:
    site = view.get("site")
    if not site:
        return None
    plan = site.get("plan") or {}
    # No boundaries: the viewer asks for them each time (VWorld's terms).
    parcels = [{"pnu": p.get("pnu", ""), "address": p.get("address", ""), "area_m2": p.get("area_m2")}
               for p in plan.get("parcels") or []]
    return {
        "area_m2": site.get("area_m2"),
        "lines": site.get("lines") or [],
        "rules": site.get("rules") or [],
        "plan": {key: plan[key] for key in ("bounds", "frame", "origin") if key in plan} | {"parcels": parcels}
        if plan else None,
    }


def _title(project_path: Path) -> str:
    try:
        brief = (Path(project_path) / "brief.md").read_text(encoding="utf-8")
    except OSError:
        brief = ""
    return (section_body(brief, "Project Name") or Path(project_path).name)[:120]


def build(project_path: Path, *, photos: bool = True, by: str = "") -> tuple[bytes, dict]:
    """
    The snapshot zip and what is in it: {papers: counts by kind, photos, photo_bytes, left_out,
    bytes}. The zip holds snapshot.json and photos/<paper id>.jpg|png (relay/shares.py).
    """
    view = board.view(project_path)
    papers, left = _shown(view)
    files: dict[str, bytes] = {}
    shared = []
    for paper in papers:
        if paper.get("kind") != "photo":
            shared.append(paper)
            continue
        if not photos:
            left["photo"] = left.get("photo", 0) + 1
            continue
        try:
            path, _media = board.photo_file(project_path, paper["id"])
            data, ext = shrink_photo(path.read_bytes())
        except (board.PaperNotFound, OSError, ValueError):
            left["photo"] = left.get("photo", 0) + 1
            continue
        name = f"photos/{paper['id']}.{ext}"
        files[name] = data
        shared.append({key: value for key, value in paper.items() if key not in ("file", "page")} | {"photo": name})
    ids = {p["id"] for p in shared}
    site = _site(view)
    address = ", ".join(p["address"] for p in ((site or {}).get("plan") or {}).get("parcels", []) if p["address"])
    snapshot = {
        "format": FORMAT,
        "title": _title(project_path),
        "by": " ".join((by or "").split())[:MAX_BY],
        "address": address,
        "made": _now(),
        "board": {
            "papers": shared,
            "layers": view.get("layers") or [],
            "figures": {k: v for k, v in (view.get("figures") or {}).items() if k in ids},
            "people": view.get("people") or [],
            "circles": view.get("circles") or [],
            "saved_view": view.get("saved_view"),
        },
        "site": site,
        "left_out": left,
    }
    files["snapshot.json"] = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("snapshot.json", files.pop("snapshot.json"))
        for name, data in files.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_STORED)  # pictures are compressed already
    counts: dict[str, int] = {}
    for paper in shared:
        counts[paper["kind"]] = counts.get(paper["kind"], 0) + 1
    zipped = out.getvalue()
    return zipped, {
        "papers": counts,
        "photos": len(files),
        "photo_bytes": sum(len(b) for b in files.values()),
        "left_out": left,
        "bytes": len(zipped),
    }


def plan(project_path: Path) -> dict:
    """What the share window shows: what would go up (photos not shrunk yet, so their size is
    the files' own) and the share as last known."""
    view = board.view(project_path)
    papers, left = _shown(view)
    counts: dict[str, int] = {}
    photo_bytes = 0
    for paper in papers:
        counts[paper["kind"]] = counts.get(paper["kind"], 0) + 1
        if paper["kind"] == "photo":
            try:
                photo_bytes += board.photo_file(project_path, paper["id"])[0].stat().st_size
            except (board.PaperNotFound, OSError):
                pass
    state = load_state(project_path)
    return {
        "title": _title(project_path),
        "site": bool(view.get("site")),
        "papers": counts,
        "photo_bytes": photo_bytes,
        "left_out": left,
        "share": _public_state(state),
        "has_key": bool(_key()),
    }


def _public_state(state: dict) -> dict:
    """The share as the screen sees it (the comments go through `comments`)."""
    keep = ("on", "comment_url", "view_url", "version", "versions", "bytes", "expires", "comments_open",
            "photos", "by", "usage", "shared_at")
    out = {key: state[key] for key in keep if key in state}
    out["on"] = bool(state.get("on"))
    out["unread"] = _unread(state)
    return out


# ---------------------------------------------------------------------------
# Uploading and turning off
# ---------------------------------------------------------------------------


def publish(project_path: Path, *, photos: bool = True, by: str = "") -> dict:
    """Upload a snapshot: a new share, or a new version of this project's share."""
    data, made = build(project_path, photos=photos, by=by)
    state = load_state(project_path)
    usage = state.get("usage")
    if state.get("on") and state.get("id"):
        try:
            share = _call("PUT", f"/relay/shares/{state['id']}", data=data, usage=usage)
        except ShareError as exc:
            if exc.code != "gone":
                raise
            state = {**state, "on": False}  # kept past its time or turned off elsewhere: start again
            share = _call("POST", "/relay/shares", data=data, usage=usage)
    else:
        share = _call("POST", "/relay/shares", data=data, usage=usage)
    state = _from_server(state, share)
    state.update({"photos": photos, "by": " ".join((by or "").split())[:MAX_BY], "shared_at": _now(), "made": made})
    _save_state(project_path, state)
    return {"share": _public_state(state), "made": made}


def change(project_path: Path, *, comments_open: bool | None = None, new_links: bool = False) -> dict:
    """Take new comments or not; or give the share new links (the old ones stop at once)."""
    state = load_state(project_path)
    if not state.get("on"):
        raise ShareError("이 프로젝트는 지금 공유하고 있지 않습니다.", 409, "off")
    body = {"new_links": bool(new_links)}
    if comments_open is not None:
        body["comments_open"] = bool(comments_open)
    share = _call("PATCH", f"/relay/shares/{state['id']}", json_body=body)
    state = _save_state(project_path, _from_server(state, share))
    return {"share": _public_state(state)}


def stop(project_path: Path) -> dict:
    """Turn the share off: the links stop, the server deletes the copy and its comments. The
    comments collected so far stay in this project."""
    state = load_state(project_path)
    if state.get("on") and state.get("id"):
        try:
            refresh_comments(project_path)
        except ShareError:
            pass
        state = load_state(project_path)
        try:
            _call("DELETE", f"/relay/shares/{state['id']}")
        except ShareError as exc:
            if exc.code != "gone":
                raise
    state = {key: value for key, value in state.items()
             if key in ("comments", "seen", "by", "photos")} | {"on": False, "stopped_at": _now()}
    _save_state(project_path, state)
    return {"share": _public_state(state)}


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def _unread(state: dict) -> int:
    seen = set(state.get("seen") or [])
    return sum(1 for c in state.get("comments") or [] if not c.get("by_owner") and c["id"] not in seen
               and not c.get("resolved"))


def _comments_answer(state: dict) -> dict:
    return {"comments": state.get("comments") or [], "unread": _unread(state), "seen": state.get("seen") or [],
            "on": bool(state.get("on"))}


def refresh_comments(project_path: Path) -> dict:
    """Collect the comments from the server (when sharing) and keep them in the project."""
    state = load_state(project_path)
    if state.get("on") and state.get("id"):
        try:
            got = _call("GET", f"/relay/shares/{state['id']}/comments")
        except ShareError as exc:
            if exc.code != "gone":
                raise
            state = {**state, "on": False}  # deleted after its keeping time; the comments stay here
        else:
            state["comments"] = [c for c in got.get("comments") or [] if isinstance(c, dict) and c.get("id")]
        _save_state(project_path, state)
    return _comments_answer(state)


def cached_comments(project_path: Path) -> dict:
    return _comments_answer(load_state(project_path))


def _sharing(project_path: Path) -> dict:
    state = load_state(project_path)
    if not state.get("on") or not state.get("id"):
        raise ShareError("공유가 꺼져 있어 댓글에 답할 수 없습니다.", 409, "off")
    return state


def reply(project_path: Path, parent: str, text: str) -> dict:
    """The designer's answer to a comment; viewers see it under the comment."""
    text = (text or "").strip()
    if not text:
        raise ShareError("답글을 적어 주세요.")
    if len(text) > MAX_REPLY:
        raise ShareError(f"답글은 {MAX_REPLY}자까지입니다.")
    state = _sharing(project_path)
    _call("POST", f"/relay/shares/{state['id']}/comments", json_body={"parent": parent, "text": text})
    return refresh_comments(project_path)


def resolve(project_path: Path, comment_id: str, resolved: bool) -> dict:
    state = load_state(project_path)
    if state.get("on") and state.get("id"):
        _call("PATCH", f"/relay/shares/{state['id']}/comments/{comment_id}", json_body={"resolved": bool(resolved)})
        return refresh_comments(project_path)
    # off: only this project's copy changes
    for comment in state.get("comments") or []:
        if comment.get("id") == comment_id:
            comment["resolved"] = bool(resolved)
    return _comments_answer(_save_state(project_path, state))


def delete_comment(project_path: Path, comment_id: str) -> dict:
    """Delete a comment (and its replies) for everyone; when the share is off, only here."""
    state = load_state(project_path)
    if state.get("on") and state.get("id"):
        _call("DELETE", f"/relay/shares/{state['id']}/comments/{comment_id}")
        return refresh_comments(project_path)
    state["comments"] = [c for c in state.get("comments") or []
                         if c.get("id") != comment_id and c.get("parent") != comment_id]
    return _comments_answer(_save_state(project_path, state))


def mark_seen(project_path: Path, ids: list[str]) -> dict:
    """The comments the designer has looked at (the 새 댓글 count leaves them out)."""
    state = load_state(project_path)
    known = {c.get("id") for c in state.get("comments") or []}
    state["seen"] = sorted(set(state.get("seen") or []) | {i for i in ids if i in known})
    return _comments_answer(_save_state(project_path, state))
