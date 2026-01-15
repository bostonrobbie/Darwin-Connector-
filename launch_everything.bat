@echo off
title IBKR and MT5 Ultimate Launcher
color 0B
cd /d "%~dp0"

echo ===================================================
echo   Starting IBKR Ultimate Trading System
echo ===================================================

echo [0/6] Cleaning up old processes...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM node.exe /T >nul 2>&1
taskkill /F /IM streamlit.exe /T >nul 2>&1
timeout /t 2 >nul

echo [Auto-Backup] Saving your latest changes to GitHub...
git add .
git commit -m "Auto-Backup on Launch"
git push origin main

:: 1. Search for TWS
echo [1/6] Looking for Trader Workstation (TWS)...

set "TWS_PATH="
if exist "C:\Jts\tws.exe" set "TWS_PATH=C:\Jts\tws.exe"
if exist "C:\Jts\980\tws.exe" set "TWS_PATH=C:\Jts\980\tws.exe"
if exist "C:\Jts\1019\tws.exe" set "TWS_PATH=C:\Jts\1019\tws.exe"
if exist "C:\Jts\1043\tws.exe" set "TWS_PATH=C:\Jts\1043\tws.exe"
if exist "%USERPROFILE%\AppData\Local\Jts\tws.exe" set "TWS_PATH=%USERPROFILE%\AppData\Local\Jts\tws.exe"

if defined TWS_PATH (
    echo     Found TWS at: %TWS_PATH%
    echo     > Opening Checklist...
    start notepad "%~dp0startup_checklist.txt"
    echo     Launching TWS...
    start "" "%TWS_PATH%"
    echo     Waiting 30 seconds for TWS to initialize...
    timeout /t 30
) else (
    echo [WARNING] Could not find 'tws.exe' in common locations.
    echo           Please ensure TWS is running manually.
    echo           Or run 'download_tools.bat' to install it.
    pause
)

:: 2. Start Bridge
echo [2/6] Starting Bridge Server...
start "IBKR Bridge" cmd /k "python "%~dp0src\main_ibkr.py""

:: 3. IBKR Tunnel managed by Connection Guard
echo [3/6] (Tunnel managed by Guard)

:: 4. Start IBKR Dashboard
echo [4/6] Starting IBKR Monitor Dashboard...
start "IBKR Monitor" cmd /k "streamlit run "%~dp0dashboard.py""

:: 5. Start MT5 Bridge (Python)
echo [5/6] Starting MT5 Bridge...
cd /d "%~dp0..\TradingView_MT5_Bridge"
start "MT5 Bridge" cmd /k "python bridge.py"

:: 6. MT5 Tunnel managed by Connection Guard
echo [6/6] (Tunnel managed by Guard)
start "" "dashboard.html"

:: 7. Start Connection Guard
echo [7/7] Starting Connection Monitor...
start "Connection Guard" cmd /k "python "%~dp0src\connection_guard.py""

:: Return to IBKR dir
cd /d "%~dp0"
