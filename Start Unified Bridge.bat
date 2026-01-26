@echo off
title Unified Bridge
cd /d "%~dp0"

:: Check if Python is available
where pythonw >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python not found! Please install Python and add it to PATH.
    pause
    exit /b 1
)

:: Launch the app (no console window)
start "" pythonw UnifiedBridge.pyw
exit
