@echo off
setlocal
cd /d "%~dp0"
title ModuBoard Industrial Workbench
if not exist ".venv\Scripts\python.exe" (
    echo Offline runtime is not installed.
    echo Run INSTALL_OFFLINE.cmd first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" tools\start_industrial.py
pause
