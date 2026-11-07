"""Run only the tests that touch what this branch changed.

    python scripts/related_tests.py           # run them (pytest -q)
    python scripts/related_tests.py --list    # only print the test files

Changed files are those that differ from where the branch left origin/main (committed,
uncommitted and new files). Each one maps to tests:

- a test file runs itself;
- sida/<path>/<name>.py runs tests/<path>/test_<name>.py and every test file that imports it;
  a JSON API module (webapp.py, *_api.py, experts/*/api.py) also runs tests/test_webapp.py;
- agents/*.md runs tests/test_agent_prompts.py; collector/ runs tests/collector/; relay/ runs tests/relay/;
- tests/conftest.py, tests/fixtures/, pyproject.toml and config.yaml run everything.

Tests that reach a changed module only through another module are not picked: CI runs the
whole suite on every pull request. Screen scripts (webui/app/*.js) are tested with node; the
command is printed when they change.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVERYTHING = "tests"
RUN_ALL = ("tests/conftest.py", "tests/fixtures/", "pyproject.toml", "config.yaml")
NODE_TESTS = (
    "node --test tests/webui/model.test.mjs tests/webui/board-model.test.mjs "
    "tests/webui/command-model.test.mjs tests/webui/talk-panel.test.mjs"
)


def changed_files(root: Path = ROOT, base: str = "origin/main") -> list[str]:
    def git(*args: str) -> list[str]:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
        return [line for line in out.stdout.splitlines() if line]

    fork = git("merge-base", "HEAD", base)[0]
    files = git("diff", "--name-only", fork) + git("ls-files", "--others", "--exclude-standard")
    return sorted(set(files))


@cache
def _imports(test_file: Path) -> frozenset[str]:
    """Dotted names a test file imports: `from sida.x import y` gives sida.x and sida.x.y."""
    names: set[str] = set()
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return frozenset(names)


def _test_files(root: Path) -> list[Path]:
    return sorted((root / "tests").rglob("test_*.py"))


def pick_tests(changed: list[str], root: Path = ROOT) -> list[str]:
    """Test paths (relative, '/'-separated) to run for these changed files. ["tests"] means all."""
    picked: set[str] = set()
    for name in changed:
        name = name.replace("\\", "/")
        path = Path(name)
        if name.startswith(RUN_ALL):
            return [EVERYTHING]
        if name.startswith("tests/") and path.name.startswith("test_") and path.suffix == ".py":
            if (root / path).exists():
                picked.add(name)
        elif name.startswith("sida/") and path.suffix == ".py":
            parts = path.with_suffix("").parts  # ("sida", "experts", "site", "context3d")
            module = ".".join(p for p in parts if p != "__init__")
            direct = Path("tests", *parts[1:-1], f"test_{parts[-1]}.py")
            if (root / direct).exists():
                picked.add(direct.as_posix())
            for test in _test_files(root):
                if module in _imports(test):
                    picked.add(test.relative_to(root).as_posix())
            if path.name in ("webapp.py", "api.py") or path.stem.endswith("_api"):
                picked.add("tests/test_webapp.py")
        elif name.startswith("scripts/") and path.suffix == ".py":
            module = ".".join(path.with_suffix("").parts)
            for test in _test_files(root):
                if module in _imports(test):
                    picked.add(test.relative_to(root).as_posix())
        elif name.startswith("agents/") and path.suffix == ".md":
            picked.add("tests/test_agent_prompts.py")
        elif name.startswith("collector/"):
            picked.add("tests/collector")
        elif name.startswith("relay/"):
            picked.add("tests/relay")
    return sorted(picked)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print the test files, do not run them")
    parser.add_argument("--base", default="origin/main", help="branch to compare with")
    args, pytest_args = parser.parse_known_args(argv)

    changed = changed_files(base=args.base)
    tests = pick_tests(changed)
    if any(n.startswith("webui/") and n.endswith((".js", ".mjs")) for n in changed):
        print(f"screen scripts changed; also run: {NODE_TESTS}")
    if args.list:
        print("\n".join(tests) if tests else "(no related tests)")
        return 0
    if not tests:
        print("no related tests for the changed files")
        return 0
    return subprocess.call([sys.executable, "-m", "pytest", *tests, *pytest_args], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
