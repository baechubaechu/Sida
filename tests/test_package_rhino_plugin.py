"""Packing the Rhino plugin for handing out (scripts/package_rhino_plugin.py), without Yak.exe."""

from __future__ import annotations

import io
import zipfile

import pytest

from scripts import package_rhino_plugin as pack
from tests.conftest import ROOT

MANIFEST = (ROOT / "rhino-plugin" / "manifest.yml").read_text(encoding="utf-8")
GUIDE = (ROOT / "rhino-plugin" / "INSTALL.ko.txt").read_text(encoding="utf-8")


def test_the_version_is_the_manifests_and_the_plugin_is_built_as_the_same_one():
    version = pack.read_version(MANIFEST)
    assert version.count(".") == 2 and f"<Version>{version}</Version>" in (
        ROOT / "rhino-plugin" / "SidaRhino" / "SidaRhino.csproj").read_text(encoding="utf-8")
    assert pack.read_version('name: sida\nversion: "1.2.3"\n') == "1.2.3"
    with pytest.raises(ValueError, match="version: 0.1.0"):
        pack.read_version("name: sida\nversion: soon\n")


def test_rhinos_package_and_the_bundle_for_people_hold_the_plugin_with_its_manifest():
    version = pack.read_version(MANIFEST)
    made = pack.packages(b"MZ plug-in", MANIFEST, GUIDE)
    assert list(made) == [f"sida-{version}-rh8_0-win.yak", f"Sida-Rhino-{version}.zip"]
    with zipfile.ZipFile(io.BytesIO(made[f"sida-{version}-rh8_0-win.yak"])) as yak:
        assert sorted(yak.namelist()) == ["SidaRhino.rhp", "manifest.yml"] and yak.read("SidaRhino.rhp") == b"MZ plug-in"
        assert yak.read("manifest.yml").decode("utf-8") == MANIFEST
    with zipfile.ZipFile(io.BytesIO(made[f"Sida-Rhino-{version}.zip"])) as bundle:
        assert sorted(bundle.namelist()) == sorted(["SidaRhino.rhp", "manifest.yml", "install.bat", "uninstall.bat", "설치 안내.txt"])
        guide = bundle.read("설치 안내.txt")
        assert guide.startswith(b"\xef\xbb\xbf") and b"\r\n" in guide and b"{version}" not in guide  # as Notepad opens it
        assert guide.decode("utf-8-sig").splitlines()[0] == f"Sida 라이노 플러그인 {version} 설치 안내"


def test_install_bat_puts_the_files_where_rhino_looks_and_says_the_version_rhino_loads():
    bat = pack.install_bat("0.3.1")
    text = bat.decode("utf-8")
    assert not bat.startswith(b"\xef\xbb\xbf") and text.startswith("@echo off\r\nchcp 65001 >nul\r\n")  # cmd reads no mark
    assert "\n" not in text.replace("\r\n", "")  # every line ends as cmd wants
    assert r'set "HOME_DIR=%APPDATA%\McNeel\Rhinoceros\packages\8.0\sida"' in text and r'set "DEST=%HOME_DIR%\0.3.1"' in text
    assert r'copy /y "%~dp0SidaRhino.rhp" "%DEST%\"' in text and r'copy /y "%~dp0manifest.yml" "%DEST%\"' in text
    # without sida\manifest.txt Rhino removes the folder when it starts
    assert r'<nul set /p="0.3.1" > "%HOME_DIR%\manifest.txt"' in text
    lines = text.split("\r\n")
    assert lines.index('if exist "%HOME_DIR%" rmdir /s /q "%HOME_DIR%"') > next(i for i, line in enumerate(lines) if "tasklist" in line)
    assert "Unblock-File" in text and "라이노가 켜져 있습니다" in text and lines[-2] == "pause"

    gone = pack.uninstall_bat().decode("utf-8")
    assert 'rmdir /s /q "%HOME_DIR%"' in gone and "0.3.1" not in gone and gone.endswith("pause\r\n")


def test_packing_writes_both_files_and_says_so_when_the_plugin_is_not_built(tmp_path, capsys):
    assert pack.main(["--rhp", str(tmp_path / "missing.rhp"), "--out", str(tmp_path / "dist")]) == 1
    assert "Build first" in capsys.readouterr().err and not (tmp_path / "dist").exists()
    rhp = tmp_path / "SidaRhino.rhp"
    rhp.write_bytes(b"MZ")
    assert pack.main(["--rhp", str(rhp), "--out", str(tmp_path / "dist")]) == 0
    version = pack.read_version(MANIFEST)
    assert sorted(p.name for p in (tmp_path / "dist").iterdir()) == sorted([f"sida-{version}-rh8_0-win.yak", f"Sida-Rhino-{version}.zip"])
