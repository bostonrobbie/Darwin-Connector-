import requests
import time
import os
import sys
from datetime import datetime
import colorama
from colorama import Fore, Style

colorama.init()

URLS = {
    "IBKR": "https://bostonrobbie-ibkr.loca.lt/health",
    "MT5": "https://major-cups-pick.loca.lt/health"
}

def log(msg, color=Fore.WHITE):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"{Fore.CYAN}[{timestamp}]{color} {msg}{Style.RESET_ALL}")

import subprocess
import atexit

# Process Store
PROCESSES = {}

def start_tunnel(name):
    """Starts a tunnel and stores the process handle."""
    cmd = ""
    if name == "IBKR":
        cmd = 'lt --port 5001 --subdomain bostonrobbie-ibkr'
    elif name == "MT5":
        cmd = 'lt --port 5000 --subdomain major-cups-pick'
    
    if cmd:
        log(f"STARTING TUNNEL: {name}", Fore.YELLOW)
        # Start new process
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        PROCESSES[name] = proc
        log(f"STARTED {name} (PID: {proc.pid})", Fore.GREEN)
        time.sleep(5) # Wait for it to spin up

def restart_tunnel(name):
    """Surgically restarts only the specific tunnel process."""
    log(f"ATTEMPTING RESTART FOR {name}...", Fore.YELLOW)
    
    # 1. Kill specific process if it exists
    if name in PROCESSES:
        proc = PROCESSES[name]
        try:
            log(f"KILLING OLD PID: {proc.pid}", Fore.MAGENTA)
            # Terminate the specific process object
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill() # Force kill if stubborn
        except Exception as e:
            log(f"Error killing {name}: {e}", Fore.RED)
        
        del PROCESSES[name]
    else:
        # Fallback: existing taskkill if we didn't start it (cleanup old mess)
        # But try to be specific if possible. For now, rely on internal tracking.
        pass

    # 2. Start new
    start_tunnel(name)

def check_status():
    all_good = True
    print("-" * 50)
    for name, url in URLS.items():
        # Ensure it's running first
        if name not in PROCESSES:
             log(f"{name}: NOT RUNNING - STARTING...", Fore.YELLOW)
             start_tunnel(name)
             
        try:
            # Short timeout
            resp = requests.get(url, timeout=5, headers={"Bypass-Tunnel-Reminder": "true"})
            if resp.status_code == 200:
                log(f"{name}: ONLINE ({url})", Fore.GREEN)
            else:
                log(f"{name}: ERROR {resp.status_code} - RESTARTING...", Fore.RED)
                restart_tunnel(name)
                all_good = False
        except Exception as e:
            log(f"{name}: DOWN (Unreachable) - RESTARTING...", Fore.RED)
            restart_tunnel(name)
            all_good = False
    
    if not all_good:
        print("\n" + "!"*50)
        log("RECOVERY ACTIONS TAKEN", Fore.YELLOW)
        print("!"*50 + "\n")
        sys.stdout.flush()

def cleanup():
    """Kill all managed processes on exit."""
    for name, proc in PROCESSES.items():
        try:
            proc.terminate()
        except:
            pass

def main():
    atexit.register(cleanup)
    print(f"{Fore.YELLOW}=== CONNECTION MANAGER ACTIVE ==={Style.RESET_ALL}")
    print("Taking control of tunnel processes...")
    
    # Initial cleanup of any rogue node processes from before
    subprocess.run("taskkill /F /IM node.exe /T", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    while True:
        check_status()
        time.sleep(30)

if __name__ == "__main__":
    main()
