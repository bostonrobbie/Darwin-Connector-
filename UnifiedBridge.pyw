"""
Unified Bridge - Standalone Application Launcher
Double-click this file to launch the complete trading system.

Features:
- Auto-launches MT5 Terminal if not running
- Starts all bridge components (MT5, TopStep, IBKR)
- Opens the web dashboard
- Runs without console window (use .pyw extension)
"""
import subprocess
import sys
import os
import webbrowser
import time
import psutil

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

def is_mt5_running():
    """Check if MT5 Terminal is already running."""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] in ['terminal64.exe', 'terminal.exe']:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def launch_mt5():
    """Launch MT5 Terminal."""
    import json

    # Load config to get MT5 path
    config_path = os.path.join(SCRIPT_DIR, 'config.json')
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)

        mt5_path = config.get('mt5', {}).get('path', '')

        if mt5_path and os.path.exists(mt5_path):
            subprocess.Popen(
                [mt5_path],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True
            )
            return True
    except Exception as e:
        pass

    return False

def is_bridge_running():
    """Check if Unified Bridge is already running by checking port 80."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', 64000))  # Singleton lock port
        sock.close()
        return False  # Port is free, bridge not running
    except socket.error:
        return True  # Port in use, bridge is running

def main():
    # Check if already running
    if is_bridge_running():
        # Just open the dashboard
        webbrowser.open("http://localhost:8502")
        return

    # Auto-launch MT5 if not running
    if not is_mt5_running():
        launch_mt5()
        # Give MT5 time to initialize
        time.sleep(10)

    # Launch the main supervisor which starts all components
    python_exe = sys.executable

    # Start the main.py supervisor in a new console window
    subprocess.Popen(
        [python_exe, "main.py"],
        cwd=SCRIPT_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

    # Wait for dashboard to start
    time.sleep(8)

    # Open the dashboard in browser
    webbrowser.open("http://localhost:8502")

if __name__ == "__main__":
    main()
