@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   Hivelight Claude Code Plugin - Installer
echo ============================================================
echo.
echo This will:
echo   1. Verify Claude Code CLI and Python 3.10+ are installed
echo   2. Register the Hivelight marketplace with Claude Code
echo   3. Install the Hivelight plugin (~30 sec)
echo   4. Download a headless browser (~150 MB, 3-5 min)
echo   5. Open Hivelight in a browser so you can log in once
echo.
echo Press Ctrl+C now to cancel, or any key to continue.
pause >nul
echo.

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

if not exist "%SCRIPT_DIR%\.claude-plugin\marketplace.json" (
    echo [error] Could not find .claude-plugin\marketplace.json next to this installer.
    echo         Make sure you fully unzipped the package before running this.
    echo.
    pause
    exit /b 1
)

REM ----- Find Python 3.10+ -----
set "PY="
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if "%PY%"=="" (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY=py -3"
    )
)
if "%PY%"=="" (
    echo [error] Python 3.10 or later is required but was not found.
    echo.
    echo Please install Python from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: on the first installer screen, tick "Add python.exe to PATH"
    echo before clicking Install Now.
    echo.
    echo After installing, close this window and double-click install.bat again.
    echo.
    pause
    exit /b 1
)
echo [ok] Found a working Python: %PY%
echo.

REM ----- Hand off to the cross-platform installer -----
%PY% "%SCRIPT_DIR%\installer.py" "%SCRIPT_DIR%"
if errorlevel 1 (
    echo.
    echo [error] Installer did not complete cleanly. See the messages above for the
    echo         exact failure and the command you can re-run.
    echo.
    pause
    exit /b 1
)

echo.
pause
