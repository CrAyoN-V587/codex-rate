@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 exit /b 1
if not exist "build" mkdir build
set "framework=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319"
"%framework%\csc.exe" /nologo /out:build\ActiveConversation.exe /r:"%framework%\WPF\UIAutomationClient.dll" /r:"%framework%\WPF\UIAutomationTypes.dll" /r:"%framework%\WPF\WindowsBase.dll" /r:System.Web.Extensions.dll native\ActiveConversation.cs
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name CodexRate --noupx --specpath build --add-binary "%~dp0build\ActiveConversation.exe:native" run.py
exit /b %errorlevel%
