@echo off
cd /d "%~dp0"
echo ==================================================
echo   TRADINGVIEW TO DARWINEX BRIDGE LAUNCHER
echo ==================================================

echo 1. Starting Webhook Tunnel (URL Generator)...
start "Webhook Tunnel" cmd /k "lt --port 5000 --subdomain major-cups-pick"

echo Waiting for tunnel...
timeout /t 5 >nul

echo 2. Starting Dashboard...
start "" "dashboard.html"

echo 3. Starting Python Bridge...
python bridge.py

pause
