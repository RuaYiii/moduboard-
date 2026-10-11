@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" tools\protocol_self_test.py
) else (
    python tools\protocol_self_test.py
)
pause
