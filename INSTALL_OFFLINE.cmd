@echo off
setlocal
cd /d "%~dp0"
title ModuBoard Offline Installer

where py >nul 2>nul
if %errorlevel%==0 (
    py -3.9 -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pip install --no-index --find-links "%CD%\offline\wheels" -r requirements-industrial.txt
if errorlevel 1 goto :failed

echo.
echo [OK] Offline runtime installed.
".venv\Scripts\python.exe" tools\field_check.py
echo.
echo Double-click START_INDUSTRIAL.cmd to run the workbench.
pause
exit /b 0

:failed
echo.
echo [ERROR] Installation failed. Python 3.9 x64 is required.
pause
exit /b 1
