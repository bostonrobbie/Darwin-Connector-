@echo off
title Unified Trading Bridge
color 0A
cd /d "%~dp0"

echo.
echo  ========================================
echo   UNIFIED TRADING BRIDGE
echo   MT5 + TopStep + IBKR + Tunnels
echo  ========================================
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

echo [*] Starting Unified Bridge Supervisor...
echo     (This starts ALL components including tunnels)
echo.

:: Run main.py - the supervisor that manages everything
python main.py

echo.
echo [!] Bridge stopped. Press any key to exit.
pause >nul
