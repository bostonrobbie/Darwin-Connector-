@echo off
title IBKR Paper Trading Bridge
color 0A

cd /d "%~dp0"

echo.
echo  ============================================
echo       IBKR Paper Trading Bridge Launcher
echo  ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python not found! Please install Python 3.8+
    pause
    exit /b 1
)

:: Create logs folder if missing
if not exist "logs" mkdir logs

:: Check if IB Gateway is running
tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I /N "ibgateway.exe">NUL
if %errorlevel% neq 0 (
    echo [WARNING] IB Gateway not detected.
    echo           Please start IB Gateway and login first!
    echo.
    echo Press any key to continue anyway...
    pause >nul
)

echo [1/2] Starting IBKR Bridge Server on port 5001...
echo.
echo  Webhook URL (local):  http://localhost:5001/webhook
echo  Webhook URL (tunnel): https://bostonrobbie-ibkr.cfargotunnel.com/webhook
echo.
echo  Config: 1 mini = 1 micro, max 3 contracts
echo  Symbol Map: NQ/NQ1! -> MNQ, ES/ES1! -> MES
echo.
echo ============================================
echo.

:: Run the bridge
python src\ibkr\bridge.py

:: If we get here, bridge exited
echo.
echo [INFO] Bridge has stopped.
pause
