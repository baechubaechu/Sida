"""Pack the built Rhino plugin for handing out, without Yak.exe (it is not on every PC, and a
package is only a zip).

    dotnet build rhino-plugin/SidaRhino/SidaRhino.csproj -c Release
    python scripts/package_rhino_plugin.py

    rhino-plugin/dist/sida-<version>-rh8_0-win.yak   Rhino's package: manifest.yml + SidaRhino.rhp
    rhino-plugin/dist/Sida-Rhino-<version>.zip       for people: the same two files, install.bat,
                                                     uninstall.bat and the guide (설치 안내.txt)

install.bat puts the files where Rhino's package manager would: under
%APPDATA%\\McNeel\\Rhinoceros\\packages\\8.0\\sida\\<version>\\, with the version in
sida\\manifest.txt (without that file Rhino removes the folder when it starts).
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "rhino-plugin"
RHP = PLUGIN / "SidaRhino" / "bin" / "Release" / "net7.0" / "SidaRhino.rhp"
PACKAGE = "sida"  # the package's name in manifest.yml, and its folder under Rhino's packages
RHINO = "8.0"
GUIDE_NAME = "설치 안내.txt"


def read_version(manifest: str) -> str:
    """The package's version in manifest.yml. Raises ValueError when it has none that reads as one."""
    found = re.search(r"^version:\s*['\"]?(\d+\.\d+\.\d+)['\"]?\s*$", manifest, re.MULTILINE)
    if not found:
        raise ValueError("manifest.yml needs a line like `version: 0.1.0`")
    return found.group(1)


def _zip(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def _bat(lines: list[str]) -> bytes:
    """A batch file as cmd reads it: CRLF lines, UTF-8 without a mark (the first lines switch cmd to UTF-8)."""
    return ("\r\n".join(["@echo off", "chcp 65001 >nul", "setlocal", *lines]) + "\r\n").encode("utf-8")


def install_bat(version: str) -> bytes:
    home = rf"%APPDATA%\McNeel\Rhinoceros\packages\{RHINO}\{PACKAGE}"
    return _bat([
        f'set "HOME_DIR={home}"',
        f'set "DEST=%HOME_DIR%\\{version}"',
        'tasklist /FI "IMAGENAME eq Rhino.exe" 2>nul | find /I "Rhino.exe" >nul',
        "if not errorlevel 1 (",
        "  echo 라이노가 켜져 있습니다. 라이노를 모두 끄고 install.bat을 다시 실행해 주세요.",
        "  goto end",
        ")",
        'if not exist "%~dp0SidaRhino.rhp" (',
        "  echo SidaRhino.rhp가 이 폴더에 없습니다. 압축을 모두 푼 뒤 그 폴더에서 실행해 주세요.",
        "  goto end",
        ")",
        'if exist "%HOME_DIR%" rmdir /s /q "%HOME_DIR%"',
        'mkdir "%DEST%"',
        "if errorlevel 1 goto failed",
        'copy /y "%~dp0SidaRhino.rhp" "%DEST%\\" >nul',
        "if errorlevel 1 goto failed",
        'copy /y "%~dp0manifest.yml" "%DEST%\\" >nul',
        "if errorlevel 1 goto failed",
        # The version Rhino loads; no line end after it, as Rhino's own package manager writes it.
        f'<nul set /p="{version}" > "%HOME_DIR%\\manifest.txt"',
        "if errorlevel 1 goto failed",
        # A file that came from the internet is blocked, and Rhino will not load a blocked plug-in.
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Get-ChildItem -LiteralPath $env:DEST | Unblock-File\" >nul 2>nul",
        f"echo Sida 라이노 플러그인 {version}을 설치했습니다.",
        "echo 라이노 8을 켜고 명령창에 SidaPanel 을 입력하세요.",
        "goto end",
        ":failed",
        "echo 설치하지 못했습니다. 이 창의 내용을 Sida 팀에 알려 주세요.",
        "echo 설치하려던 곳: %DEST%",
        ":end",
        "pause",
    ])


def uninstall_bat() -> bytes:
    home = rf"%APPDATA%\McNeel\Rhinoceros\packages\{RHINO}\{PACKAGE}"
    return _bat([
        f'set "HOME_DIR={home}"',
        'tasklist /FI "IMAGENAME eq Rhino.exe" 2>nul | find /I "Rhino.exe" >nul',
        "if not errorlevel 1 (",
        "  echo 라이노가 켜져 있습니다. 라이노를 모두 끄고 다시 실행해 주세요.",
        "  goto end",
        ")",
        'if exist "%HOME_DIR%" rmdir /s /q "%HOME_DIR%"',
        'if exist "%HOME_DIR%" (echo 지우지 못했습니다: %HOME_DIR%) else (echo Sida 라이노 플러그인을 지웠습니다.)',
        ":end",
        "pause",
    ])


def guide(text: str, version: str) -> bytes:
    """The guide as Notepad opens it on any Windows: CRLF lines, UTF-8 with its mark."""
    lines = text.replace("{version}", version).replace("\r\n", "\n").rstrip("\n").split("\n")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


def packages(rhp: bytes, manifest: str, guide_text: str) -> dict[str, bytes]:
    """The files to hand out, by file name: Rhino's package and the bundle for people."""
    version = read_version(manifest)
    both = {"manifest.yml": manifest.encode("utf-8"), "SidaRhino.rhp": rhp}
    return {
        f"{PACKAGE}-{version}-rh{RHINO.replace('.', '_')}-win.yak": _zip(both),
        f"Sida-Rhino-{version}.zip": _zip({
            **both, "install.bat": install_bat(version), "uninstall.bat": uninstall_bat(), GUIDE_NAME: guide(guide_text, version)}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rhp", type=Path, default=RHP, help="the built plug-in (default: the Release build)")
    parser.add_argument("--out", type=Path, default=PLUGIN / "dist", help="where the files go")
    args = parser.parse_args(argv)
    if not args.rhp.is_file():
        print(f"{args.rhp} is not there. Build first: dotnet build rhino-plugin/SidaRhino/SidaRhino.csproj -c Release", file=sys.stderr)
        return 1
    made = packages(args.rhp.read_bytes(), (PLUGIN / "manifest.yml").read_text(encoding="utf-8"),
                    (PLUGIN / "INSTALL.ko.txt").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in made.items():
        (args.out / name).write_bytes(data)
        print(f"{args.out / name} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
