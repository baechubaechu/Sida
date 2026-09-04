@echo off
setlocal EnableExtensions
rem ---------------------------------------------------------------------------
rem  Sida launcher for Windows. Double-click or run from a terminal.
rem
rem    run.bat                 chat (project hub)
rem    run.bat <project|brief> open a project or start from a brief .md
rem    run.bat setup           language + OpenRouter API key
rem    run.bat pipeline <brief.md>   non-interactive sequential run (run.py)
rem    run.bat test            run the test suite
rem    run.bat update          reinstall dependencies
rem
rem  First run creates .venv and installs requirements. Needs Python 3.10+.
rem ---------------------------------------------------------------------------

cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "VENV=.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "STAMP=%VENV%\requirements.installed"

if not exist "%VPY%" goto :create_venv
goto :deps

:create_venv
call :find_python || goto :no_python
echo [sida] Creating virtual environment (.venv) ...
%PYCMD% -m venv "%VENV%" || goto :venv_failed
"%VPY%" -m pip install --quiet --upgrade pip >nul 2>&1

:deps
set "NEED_INSTALL="
if /i "%~1"=="update" set "NEED_INSTALL=1"
if not exist "%STAMP%" set "NEED_INSTALL=1"
if not defined NEED_INSTALL (
    fc /b requirements.txt "%STAMP%" >nul 2>&1 || set "NEED_INSTALL=1"
)
if defined NEED_INSTALL (
    echo [sida] Installing dependencies ...
    "%VPY%" -m pip install --quiet -r requirements.txt || goto :pip_failed
    copy /y requirements.txt "%STAMP%" >nul
)
if /i "%~1"=="update" (
    echo [sida] Dependencies are up to date.
    goto :end
)

rem ---------------------------------------------------------------- dispatch
if /i "%~1"=="setup"    ( "%VPY%" setup_env.py %2 %3 & goto :end )
if /i "%~1"=="test"     ( "%VPY%" -m pip install --quiet pytest >nul 2>&1 & "%VPY%" -m pytest %2 %3 %4 & goto :end )
if /i "%~1"=="pipeline" ( shift & "%VPY%" run.py %1 %2 %3 & goto :end )
"%VPY%" chat.py %*
goto :end

rem ---------------------------------------------------------------- helpers
:find_python
set "PYCMD="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PYCMD=py -3"
if not defined PYCMD (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD exit /b 1
exit /b 0

:no_python
echo.
echo [sida] Python 3.10 or newer was not found.
echo        Install it from https://www.python.org/downloads/windows/
echo        and tick "Add python.exe to PATH" during setup, then run this file again.
goto :fail

:venv_failed
echo.
echo [sida] Could not create the virtual environment (.venv).
goto :fail

:pip_failed
echo.
echo [sida] Dependency installation failed. Check your internet connection and retry:
echo        run.bat update
goto :fail

:fail
if "%SIDA_NO_PAUSE%"=="" pause
exit /b 1

:end
endlocal
