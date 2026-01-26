@echo off
title Unified Bridge VPS Setup 🚀
color 0A

echo ===================================================
echo       Unified Bridge - VPS One-Click Setup
echo ===================================================
echo.

:: 1. Check Python
echo [1/4] Checking Python Installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is NOT installed or not in PATH.
    echo Please install Python 3.10+ from python.org and tick "Add to PATH".
    pause
    exit /b
)
python --version
echo [OK] Python found.
echo.

:: 2. Install Dependencies
echo [2/4] Installing Required Libraries (pip)...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies. Check internet connection.
    pause
    exit /b
)
echo [OK] Dependencies installed.
echo.

:: 3. Create Shortcut
echo [3/4] Creating Desktop Shortcut...
call create_shortcut.bat
echo [OK] Shortcut created.
echo.

:: 4. Config Check
echo [4/4] Validation Config Paths...
if exist config.json (
    echo [INFO] Found config.json. Checking paths...
    
    :: Simple check for common MT5 path
    if not exist "C:\Program Files\MetaTrader 5\terminal64.exe" (
        echo [WARNING] Default MT5 path not found at: C:\Program Files\MetaTrader 5\terminal64.exe
        echo You may need to edit config.json if you installed MT5 elsewhere.
    ) else (
        echo [OK] MT5 default path exists.
    )
) else (
    echo [WARNING] config.json missing! Please ensure you copied all files.
)

echo.
echo ===================================================
echo           SETUP COMPLETE! READY TO TRADE
echo ===================================================
echo 1. Edit config.json if you have custom API keys or paths.
echo 2. Double-click "Start Unified Bridge" on your Desktop.
echo.
pause
