@echo off
cd /d "%~dp0"
echo ==========================================
echo       JARVIS LOCAL AGENT V11 - SETUP
echo ==========================================
echo.
set /p GW=URL do Gateway Render (ex: https://projeto2-2-3ldg.onrender.com): 
set /p TK=LOCAL_AGENT_TOKEN (mesmo token do Render):
>config.json echo {"gateway_url":"%GW%","token":"%TK%","poll_seconds":2}
echo.
echo Configurado. Agora execute start_agent.bat
pause
