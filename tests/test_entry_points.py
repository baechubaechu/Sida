"""The launcher files in the repo root (what run.bat and the docs call) start the package modules."""

from __future__ import annotations

import importlib
import runpy

import pytest

from sida import harness
from tests.conftest import ROOT


@pytest.mark.parametrize("name", ["chat", "run", "setup_env", "webapp"])
def test_root_launcher_points_at_the_package_module(name):
    loaded = runpy.run_path(str(ROOT / f"{name}.py"), run_name="not_main")  # must not start anything
    assert loaded["main"] is importlib.import_module(f"sida.{name}").main


def test_root_is_the_repo_root_not_the_package_folder():
    assert harness.ROOT == ROOT
    assert (harness.ROOT / "config.yaml").is_file() and (harness.ROOT / "agents").is_dir()
