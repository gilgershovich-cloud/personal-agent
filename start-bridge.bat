@echo off
echo Starting Personal Agent Local Bridge...
echo.

REM Set your values here after deploying:
set BACKEND_URL=wss://personal-agent.up.railway.app/ws/bridge
set AGENT_TOKEN=change-me-secret

cd /d "%~dp0local_bridge"
python bridge.py
pause
