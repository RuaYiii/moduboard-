@echo off
setlocal
cd /d "%~dp0"
title ModuBoard Installer

where py >nul 2>nul
if %errorlevel%==0 (
    py -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo [OK] ModuBoard is ready.
".venv\Scripts\python.exe" tools\field_check.py
echo.
echo Double-click START_INDUSTRIAL.cmd to open the workbench.
pause
exit /b 0

:failed
echo.
echo [ERROR] Installation failed. Check Python and network access.
pause
exit /b 1
