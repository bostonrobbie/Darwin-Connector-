@echo off
title Unified Bridge Launcher
cd /d "%~dp0"
echo Starting Unified Bridge...
start "" pythonw launch_dashboard.pyw
exit
