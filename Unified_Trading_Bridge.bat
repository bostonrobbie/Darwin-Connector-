@echo off
title Unified Trading Bridge
color 0A
cd /d "%~dp0"

echo.
echo  ╔════════════════════════════════════════════════════════╗
echo  ║         UNIFIED TRADING BRIDGE LAUNCHER                ║
echo  ║         MT5 + TopStep + IBKR                           ║
echo  ╚════════════════════════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python not found! Please install Python 3.8+
    pause
    exit /b 1
)

:: Create logs folder
if not exist "logs" mkdir logs

echo [1/5] Cleaning up old processes...
taskkill /F /IM streamlit.exe /T >nul 2>&1
timeout /t 1 >nul

echo [2/5] Checking IB Gateway...
tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I /N "ibgateway.exe">NUL
if %errorlevel% neq 0 (
    echo       [!] IB Gateway not running - IBKR trades will fail
    echo       [!] Please start IB Gateway manually if needed
) else (
    echo       [OK] IB Gateway detected
)

echo [3/5] Starting IBKR Bridge (port 5001)...
start "IBKR Bridge" /min cmd /c "cd /d "%~dp0" && python src\ibkr\bridge.py"
timeout /t 2 >nul

echo [4/5] Starting MT5 Bridge (port 80)...
start "MT5 Bridge" /min cmd /c "cd /d "%~dp0" && python src\mt5\bridge.py"
timeout /t 2 >nul

echo [5/5] Starting Dashboard (port 8502)...
start "Dashboard" cmd /c "cd /d "%~dp0" && streamlit run dashboard\app.py --server.port 8502 --server.headless true"
timeout /t 3 >nul

echo.
echo  ════════════════════════════════════════════════════════════
echo.
echo   All services started!
echo.
echo   Dashboard:     http://localhost:8502
echo   IBKR Webhook:  http://localhost:5001/webhook
echo   MT5 Webhook:   http://localhost:80/webhook
echo.
echo   Tunnel URLs (for TradingView):
echo   IBKR: https://bostonrobbie-ibkr.cfargotunnel.com/webhook
echo   MT5:  https://major-cups-pick.loca.lt/webhook
echo.
echo  ════════════════════════════════════════════════════════════
echo.
echo   Press any key to open the Dashboard in your browser...
pause >nul

start "" "http://localhost:8502"

echo.
echo   Dashboard opened. This window can be minimized.
echo   Press any key to STOP all services and exit.
pause >nul

echo.
echo Stopping all services...
taskkill /F /FI "WINDOWTITLE eq IBKR Bridge*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq MT5 Bridge*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Dashboard*" >nul 2>&1
echo Done.
