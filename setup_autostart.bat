@echo off
set "TARGET=%~dp0run_unified.bat"
set "STARTUP=%USERPROFILE%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\UnifiedBridge.lnk"

echo Adding to Windows Startup...

set PWS=powershell.exe -ExecutionPolicy Bypass -NoProfile -NonInteractive -Command
%PWS% "$s=(New-Object -COM WScript.Shell).CreateShortcut('%STARTUP%');$s.TargetPath='%TARGET%';$s.WorkingDirectory='%~dp0';$s.IconLocation='shell32.dll,13';$s.WindowStyle=7;$s.Save()"

:: WindowStyle=7 means Minimized.
echo Done! Bridge will start automatically on boot.
pause
