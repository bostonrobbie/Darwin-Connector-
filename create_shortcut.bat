@echo off
set "TARGET=%~dp0run_unified.bat"
set "SHORTCUT=%USERPROFILE%\Desktop\Start Unified Bridge.lnk"
set "ICON=%~dp0dashboard\app.py" 
:: Python files don't have icons, but we can default to cmd or python executable icon later if needed.
:: For now, just generic shortcut.

echo Creating shortcut to %TARGET%...

set PWS=powershell.exe -ExecutionPolicy Bypass -NoProfile -NonInteractive -Command
set "ICON=%SystemRoot%\System32\cmd.exe"
%PWS% "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT%');$s.TargetPath='%TARGET%';$s.WorkingDirectory='%~dp0';$s.IconLocation='%ICON%';$s.Save()"

echo Done! Shortcut on Desktop.
pause
