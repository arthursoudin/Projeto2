@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Jarvis Local Agent
py -m pip install -q -r requirements.txt
py agent.py
pause
