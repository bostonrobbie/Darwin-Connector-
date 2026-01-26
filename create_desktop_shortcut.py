"""
Creates a desktop shortcut for the Unified Bridge Dashboard.
Run this once to create the shortcut.
"""
import os
import sys

def create_shortcut():
    try:
        import winshell
        from win32com.client import Dispatch
    except ImportError:
        print("Installing required packages...")
        os.system(f'"{sys.executable}" -m pip install pywin32 winshell')
        import winshell
        from win32com.client import Dispatch

    # Paths
    desktop = winshell.desktop()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(script_dir, "launch_dashboard.pyw")
    shortcut_path = os.path.join(desktop, "Unified Bridge.lnk")
    icon_path = os.path.join(script_dir, "dashboard", "icon.ico")

    # Create shortcut
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = sys.executable.replace("python.exe", "pythonw.exe")
    shortcut.Arguments = f'"{target}"'
    shortcut.WorkingDirectory = script_dir
    shortcut.Description = "Launch Unified Trading Bridge Dashboard"

    # Use custom icon if exists, otherwise use Python icon
    if os.path.exists(icon_path):
        shortcut.IconLocation = icon_path
    else:
        shortcut.IconLocation = sys.executable

    shortcut.save()
    print(f"Desktop shortcut created: {shortcut_path}")
    print("You can now double-click 'Unified Bridge' on your desktop!")

if __name__ == "__main__":
    create_shortcut()
    input("Press Enter to close...")
