@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Open
set "clipzone_exit=%errorlevel%"
if not "%clipzone_exit%"=="0" pause
exit /b %clipzone_exit%
