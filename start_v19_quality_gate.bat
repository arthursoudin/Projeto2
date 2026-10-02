@echo off
setlocal
cd /d %~dp0
python quality_gate.py
if errorlevel 1 pause & exit /b 1
python -m pytest -q tests/test_v19_command_os.py
if errorlevel 1 pause & exit /b 1
python -m py_compile app.py gateway.py orchestrator.py local_agent\agent.py v19_command_os.py
if errorlevel 1 pause & exit /b 1
echo.
echo V19 QUALITY GATE: PASS
pause
