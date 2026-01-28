"""
Unified Bridge Dashboard Launcher
Double-click this file to launch the trading dashboard.
Uses .pyw extension to run without console window.
"""
import subprocess
import sys
import os
import webbrowser
import time

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

def main():
    # Launch the main supervisor which starts all components
    python_exe = sys.executable

    # Start the main.py supervisor
    subprocess.Popen(
        [python_exe, "main.py"],
        cwd=SCRIPT_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

    # Wait a moment for dashboard to start
    time.sleep(5)

    # Open the dashboard in browser
    webbrowser.open("http://localhost:8502")

if __name__ == "__main__":
    main()
