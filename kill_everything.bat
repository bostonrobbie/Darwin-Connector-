@echo off
title KILL ALL TRADING BRIDGES
color 0C
echo.
echo ==================================================
echo   STOPPING ALL TRADING BRIDGES
echo ==================================================
echo.
echo [1/3] Killing Python Processes (IBKR & MT5 Bridges)...
taskkill /F /IM python.exe /T

echo [2/3] Killing Tunnels (node.exe)...
taskkill /F /IM node.exe /T

echo [3/3] Killing Dashboard (Streamlit)...
:: This is usually covered by pythonkill, but double checking
taskkill /F /IM streamlit.exe /T

echo.
echo ALL STOPPED.
pause
