' CreateDesktopShortcut.vbs
' Double-click this file to create a desktop shortcut for Unified Bridge

Set WshShell = WScript.CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get paths
strDesktop = WshShell.SpecialFolders("Desktop")
strScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
strBatchFile = strScriptDir & "\Unified_Bridge.bat"
strShortcut = strDesktop & "\Unified Bridge.lnk"

' Create shortcut
Set oShortcut = WshShell.CreateShortcut(strShortcut)
oShortcut.TargetPath = strBatchFile
oShortcut.WorkingDirectory = strScriptDir
oShortcut.Description = "Launch Unified Trading Bridge Dashboard"
oShortcut.IconLocation = "shell32.dll,12"
oShortcut.Save

MsgBox "Desktop shortcut created!" & vbCrLf & vbCrLf & "You can now launch Unified Bridge from your desktop.", vbInformation, "Unified Bridge"
