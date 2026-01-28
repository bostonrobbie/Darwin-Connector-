@echo off
cd /d "%~dp0"

set "TARGET=%~dp0Launch_IBKR_Bridge.bat"
set "SHORTCUT=%USERPROFILE%\Desktop\IBKR Bridge.lnk"
set "WORKDIR=%~dp0"

echo Creating IBKR Bridge Desktop Shortcut...

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%WORKDIR%'; $s.Description = 'Launch IBKR Paper Trading Bridge'; $s.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo ================================================
    echo  SUCCESS! "IBKR Bridge" shortcut created!
    echo  Look for it on your Desktop.
    echo ================================================
) else (
    echo.
    echo [ERROR] Failed to create shortcut.
)

pause
