@echo off
title Unified Bridge System
cd /d "%~dp0"

:start
echo Starting Unified Bridge...
python main.py
echo Bridge exited. Restarting in 5 seconds...
timeout /t 5
goto start
