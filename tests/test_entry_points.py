"""The launcher files in the repo root (what run.bat and the docs call) start the package modules."""

from __future__ import annotations

import importlib
import runpy

import pytest

from sida import config as sida_config
from sida import errors
from tests.conftest import ROOT


@pytest.mark.parametrize("name", ["chat", "run", "setup_env", "webapp"])
def test_root_launcher_points_at_the_package_module(name):
    loaded = runpy.run_path(str(ROOT / f"{name}.py"), run_name="not_main")  # must not start anything
    assert loaded["main"] is importlib.import_module(f"sida.{name}").main


def test_root_is_the_repo_root_not_the_package_folder():
    assert sida_config.ROOT == ROOT
    assert (sida_config.ROOT / "config.yaml").is_file() and (sida_config.ROOT / "agents").is_dir()


@pytest.mark.parametrize("name", ["chat", "run", "setup_env", "webapp"])
def test_cli_reports_core_error_once_and_exits(name, monkeypatch, capsys):
    module = importlib.import_module(f"sida.{name}")

    def broken(*_args, **_kwargs):
        errors.fail("테스트 설정 오류", code=3)

    if name == "chat":
        monkeypatch.setattr(module, "ensure_app_setup", broken)
        monkeypatch.setattr("sys.argv", ["chat.py"])
    elif name == "run":
        monkeypatch.setattr(module, "run", broken)
        monkeypatch.setattr("sys.argv", ["run.py", "brief.md"])
    elif name == "setup_env":
        monkeypatch.setattr(module, "run_setup", broken)
        monkeypatch.setattr(module, "read_api_key_from_env", lambda: "")
        monkeypatch.setattr("sys.argv", ["setup_env.py"])
    else:
        monkeypatch.setattr(module, "create_app", broken)
        monkeypatch.setattr("sys.argv", ["webapp.py", "--no-browser"])
    with pytest.raises(SystemExit) as info:
        module.main()
    assert info.value.code == 3
    assert capsys.readouterr().err == "Error: 테스트 설정 오류\n"


def test_missing_api_key_is_a_core_error(monkeypatch, capsys):
    from sida import setup_env

    monkeypatch.setattr(setup_env, "read_api_key_from_env", lambda: "")
    with pytest.raises(errors.SidaError) as info:
        setup_env.ensure_api_key(interactive=False)
    assert isinstance(info.value, Exception)
    assert capsys.readouterr() == ("", "")
