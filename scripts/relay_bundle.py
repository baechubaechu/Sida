"""Pack what the relay server's Docker image is built from, out of one commit.

    python scripts/relay_bundle.py                 # origin/main -> relay-bundle.tar.gz
    python scripts/relay_bundle.py --ref HEAD -o out.tar.gz

The bundle holds the repository's relay/ folder with two copies inside it, as the Dockerfile wants:

    relay/sida/     the app's sida/ package (the ground and 건축물대장 lookups use it as it is)
    relay/viewer/   the share viewer's screen files from webui/app (only the ones in VIEWER_FILES)

So the viewer is part of the image and changes with every rebuild; nothing is copied to the server
by hand any more. It is made from a commit (git archive), never from the working folder, so files
that are not committed do not reach the server. On the server (relay/README.md, "설치"):

    rm -rf /tmp/r && mkdir /tmp/r && tar -xzf relay-bundle.tar.gz -C /tmp/r
    rm -rf /opt/sida-kr/relay/sida /opt/sida-kr/relay/viewer && rsync -a /tmp/r/relay/ /opt/sida-kr/relay/
    cd /opt/sida-kr && docker compose up -d --build relay
"""

from __future__ import annotations

import argparse
import ast
import gzip
import io
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("relay", "sida", "webui/app")
SKIP = {"__pycache__"}


def viewer_files(app_source: str) -> set[str]:
    """VIEWER_FILES in relay/app.py, read without importing it (no FastAPI needed to pack)."""
    for node in ast.parse(app_source).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "VIEWER_FILES" for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise ValueError("relay/app.py has no VIEWER_FILES")


def bundle(source_tar: bytes) -> bytes:
    """The relay bundle (tar.gz) from a tar of the repository's relay/, sida/ and webui/app/.

    Raises ValueError when a file the viewer serves is missing, so a broken viewer is not shipped.
    """
    files: dict[str, tuple[tarfile.TarInfo, bytes]] = {}
    with tarfile.open(fileobj=io.BytesIO(source_tar)) as src:
        for info in src.getmembers():
            path = PurePosixPath(info.name)
            if info.isfile() and not SKIP & set(path.parts):
                files[path.as_posix()] = (info, src.extractfile(info).read())
    if "relay/app.py" not in files:
        raise ValueError("the source has no relay/app.py")
    wanted = viewer_files(files["relay/app.py"][1].decode("utf-8"))
    missing = sorted(n for n in wanted if f"webui/app/{n}" not in files)
    if missing:
        raise ValueError(f"viewer files missing from webui/app: {', '.join(missing)}")

    out: list[tuple[str, tarfile.TarInfo, bytes]] = []
    for name, (info, data) in sorted(files.items()):
        if name.startswith("relay/") and not name.startswith(("relay/sida/", "relay/viewer/")):
            out.append((name, info, data))
        elif name.startswith("sida/"):
            out.append((f"relay/{name}", info, data))
        elif name.startswith("webui/app/") and name.removeprefix("webui/app/") in wanted:
            out.append((f"relay/viewer/{name.removeprefix('webui/app/')}", info, data))

    buffer = io.BytesIO()
    # mtime 0 and sorted names: the same commit packs to the same bytes.
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for name, info, data in out:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), info.mode & 0o755 or 0o644, info.mtime
            tar.addfile(entry, io.BytesIO(data))
    return buffer.getvalue()


def git_archive(ref: str) -> bytes:
    return subprocess.run(["git", "archive", "--format=tar", ref, *SOURCES], cwd=ROOT,
                          check=True, capture_output=True).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="origin/main", help="the commit to pack (default origin/main)")
    parser.add_argument("-o", "--out", default="relay-bundle.tar.gz", help="where to write the bundle")
    args = parser.parse_args(argv)
    try:
        data = bundle(git_archive(args.ref))
    except (subprocess.CalledProcessError, ValueError) as e:
        detail = e.stderr.decode(errors="replace").strip() if isinstance(e, subprocess.CalledProcessError) else e
        print(f"relay bundle: {detail}", file=sys.stderr)
        return 1
    Path(args.out).write_bytes(data)
    print(f"{args.out}: {len(data) // 1024} KB from {args.ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
