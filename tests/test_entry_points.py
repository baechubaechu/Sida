"""The launcher in the repo root (what run.bat and the docs call) starts the package module."""

from __future__ import annotations

import importlib
import runpy

import pytest

from sida import config as sida_config
from sida import errors
from tests.conftest import ROOT


@pytest.mark.parametrize("name", ["webapp"])
def test_root_launcher_points_at_the_package_module(name):
    loaded = runpy.run_path(str(ROOT / f"{name}.py"), run_name="not_main")  # must not start anything
    assert loaded["main"] is importlib.import_module(f"sida.{name}").main


def test_root_is_the_repo_root_not_the_package_folder():
    assert sida_config.ROOT == ROOT
    assert (sida_config.ROOT / "config.yaml").is_file() and (sida_config.ROOT / "agents").is_dir()


def test_webapp_reports_core_error_once_and_exits(monkeypatch, capsys):
    from sida import webapp

    def broken(*_args, **_kwargs):
        errors.fail("테스트 설정 오류", code=3)

    monkeypatch.setattr(webapp, "create_app", broken)
    monkeypatch.setattr("sys.argv", ["webapp.py", "--no-browser"])
    with pytest.raises(SystemExit) as info:
        webapp.main()
    assert info.value.code == 3
    assert capsys.readouterr().err == "Error: 테스트 설정 오류\n"


def test_only_the_web_launcher_is_left():
    assert not any((ROOT / f"{name}.py").exists() for name in ("chat", "run", "setup_env"))
