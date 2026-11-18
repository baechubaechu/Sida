"""Packing the relay server's image sources (scripts/relay_bundle.py): relay/ with the app's sida/
and the share viewer's files inside it, as relay/Dockerfile copies them."""

from __future__ import annotations

import io
import tarfile

import pytest

from relay import app as relay
from scripts import relay_bundle
from tests.conftest import ROOT

APP = (ROOT / "relay" / "app.py").read_text(encoding="utf-8")


def source_tar(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o664
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def members(bundle: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}


def repo_like(**extra: str) -> dict[str, str]:
    files = {"relay/app.py": APP, "relay/Dockerfile": "FROM python", "relay/static/vworld3d.html": "3d",
             "relay/__pycache__/app.cpython-312.pyc": "x", "relay/sida/stale.py": "old copy",
             "sida/__init__.py": "", "sida/experts/site/ledger_pack.py": "ledger",
             "webui/app/index.html": "the app", "webui/app/table.js": "the board"}
    files.update({f"webui/app/{name}": f"viewer {name}" for name in relay.VIEWER_FILES})
    files.update(extra)
    return files


def test_the_bundle_is_relay_with_the_app_code_and_only_the_viewers_screen_files():
    got = members(relay_bundle.bundle(source_tar(repo_like())))
    assert got["relay/app.py"] == APP.encode("utf-8")
    assert "relay/Dockerfile" in got and "relay/static/vworld3d.html" in got
    assert got["relay/sida/experts/site/ledger_pack.py"] == b"ledger" and "relay/sida/__init__.py" in got
    viewer = {name.removeprefix("relay/viewer/") for name in got if name.startswith("relay/viewer/")}
    assert viewer == relay.VIEWER_FILES  # index.html, table.js and the rest of the app stay out
    assert got["relay/viewer/vendor/three.js"] == b"viewer vendor/three.js"
    assert not any("__pycache__" in name for name in got)
    assert "relay/sida/stale.py" not in got  # the copies come from sida/ and webui/app, not old ones
    assert relay_bundle.bundle(source_tar(repo_like())) == relay_bundle.bundle(source_tar(repo_like()))


def test_a_viewer_file_missing_from_the_app_stops_the_bundle():
    files = repo_like()
    del files["webui/app/share-view.js"]
    with pytest.raises(ValueError, match="share-view.js"):
        relay_bundle.bundle(source_tar(files))
    with pytest.raises(ValueError, match="relay/app.py"):
        relay_bundle.bundle(source_tar({"sida/__init__.py": ""}))


def test_the_viewer_list_is_read_from_the_relay_without_importing_it_and_the_image_serves_it():
    assert relay_bundle.viewer_files(APP) == relay.VIEWER_FILES
    for name in relay.VIEWER_FILES:
        assert (ROOT / "webui" / "app" / name).is_file(), name
    dockerfile = (ROOT / "relay" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY viewer /srv/viewer/" in dockerfile and "SIDA_VIEWER_DIR=/srv/viewer" in dockerfile
    assert "COPY sida /srv/sida/" in dockerfile
