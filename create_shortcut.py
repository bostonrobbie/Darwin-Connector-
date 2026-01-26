"""
Creates a desktop shortcut for Unified Bridge.
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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    desktop = winshell.desktop()
    shortcut_path = os.path.join(desktop, "Unified Bridge.lnk")

    # Find pythonw.exe
    python_dir = os.path.dirname(sys.executable)
    pythonw_path = os.path.join(python_dir, "pythonw.exe")

    if not os.path.exists(pythonw_path):
        pythonw_path = sys.executable  # Fallback

    # Target script
    target_script = os.path.join(script_dir, "UnifiedBridge.pyw")

    # Create shortcut
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = pythonw_path
    shortcut.Arguments = f'"{target_script}"'
    shortcut.WorkingDirectory = script_dir
    shortcut.Description = "Unified Bridge - Multi-Broker Trading System"

    # Try to set icon (use a generic trading icon or Python icon)
    icon_path = os.path.join(script_dir, "icon.ico")
    if os.path.exists(icon_path):
        shortcut.IconLocation = icon_path
    else:
        # Use Python icon as fallback
        shortcut.IconLocation = f"{sys.executable},0"

    shortcut.save()

    print(f"Shortcut created: {shortcut_path}")
    print("You can now launch Unified Bridge from your desktop!")

if __name__ == "__main__":
    create_shortcut()
    input("\nPress Enter to exit...")
