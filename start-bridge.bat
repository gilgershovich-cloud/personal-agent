@echo off
echo Starting Personal Agent Local Bridge...
echo.

REM Set your values here after deploying:
set BACKEND_URL=wss://personal-agent-q29j.onrender.com/ws/bridge
set AGENT_TOKEN=gil1988

cd /d "%~dp0local_bridge"
py bridge.py
pause
