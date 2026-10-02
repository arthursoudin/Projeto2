@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py uptime_loop.py) else (python uptime_loop.py)
pause
