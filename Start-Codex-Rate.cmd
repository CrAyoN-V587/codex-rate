@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0CodexRate.exe" (
    start "" "%~dp0CodexRate.exe"
    exit /b
)
if exist "%~dp0dist\CodexRate.exe" (
    start "" "%~dp0dist\CodexRate.exe"
    exit /b
)
where pythonw.exe >nul 2>nul
if errorlevel 1 (
    echo Python with Tk is required to run from source. Use dist\CodexRate.exe instead.
    pause
    exit /b 1
)
start "" pythonw.exe "%~dp0run.py"
