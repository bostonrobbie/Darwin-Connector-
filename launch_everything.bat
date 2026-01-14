@echo off
title IBKR Ultimate Launcher
color 0B

echo ===================================================
echo   Starting IBKR Ultimate Trading System
echo ===================================================

:: 1. Search for TWS
echo [1/4] Looking for Trader Workstation (TWS)...

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
echo [2/4] Starting Bridge Server...
start "IBKR Bridge" cmd /k "python src/main_ibkr.py"

:: 3. Start Tunnel
echo [3/4] Starting Tunnel...
cmd /k "lt --port 5001"
