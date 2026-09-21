@echo off
REM Hivelight session refresh — double-click this when the silent refresh
REM fails (about once every 30 days when Hivelight's login cookie expires).
REM Opens a browser so you can log in again; everything else is automated.
setlocal

set "PLUGIN_DIR=%~dp0"
if "%PLUGIN_DIR:~-1%"=="\" set "PLUGIN_DIR=%PLUGIN_DIR:~0,-1%"
set "SETUP=%PLUGIN_DIR%\skills\hivelight\lib\setup.py"

if not exist "%SETUP%" (
    echo [error] Could not find setup.py next to this script at:
    echo   %SETUP%
    echo The plugin folder may be incomplete. Re-run install.bat to fix this.
    pause
    exit /b 1
)

REM Find Python (3.10+)
set "PY="
where python >nul 2>&1 && set "PY=python"
if "%PY%"=="" (
    where py >nul 2>&1 && set "PY=py -3"
)
if "%PY%"=="" (
    echo [error] Python is not on PATH. Re-run install.bat to set things up.
    pause
    exit /b 1
)

echo ============================================================
echo   Hivelight session refresh
echo ============================================================
echo.
echo Opening a browser. Log in if prompted; otherwise the refresh
echo finishes automatically once it reaches the dashboard.
echo.

%PY% "%SETUP%"
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
    echo [done] Session refreshed. Restart Claude Code if it was open.
) else (
    echo [error] Refresh did not complete cleanly. Try install.bat as a fallback.
)
pause
