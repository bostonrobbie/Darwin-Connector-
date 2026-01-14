@echo off
set "SCRIPT_PATH=%~dp0launch_everything.bat"
set "ICON_PATH=%~dp0src\icon.ico" 
:: Fallback to no icon if missing
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT_PATH=%DESKTOP%\Start IBKR Bridge.lnk"

echo Creating Desktop Shortcut...
echo Target: %SCRIPT_PATH%
echo Desktop: %DESKTOP%

powershell "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT_PATH%');$s.TargetPath='%SCRIPT_PATH%';$s.Save()"

echo.
echo ========================================================
echo SUCCESS! Look for "Start IBKR Bridge" on your Desktop.
echo ========================================================
pause
