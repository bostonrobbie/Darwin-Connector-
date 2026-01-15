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

def restart_tunnel(name):
    """Kills and restarts the tunnel process."""
    log(f"ATTEMPTING RESTART FOR {name}...", Fore.YELLOW)
    
    # 1. Kill old process
    try:
        # We kill node.exe explicitly as it runs localtunnel
        subprocess.run("taskkill /F /IM node.exe /T", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    except:
        pass
        
    # 2. Start new process (background, no new window)
    cmd = ""
    if name == "IBKR":
        cmd = 'lt --port 5001 --subdomain bostonrobbie-ibkr'
    elif name == "MT5":
        cmd = 'lt --port 5000 --subdomain major-cups-pick'
        
    if cmd:
        # Use shell=True to find 'lt' in path (it's a node script/batch file)
        # Redirect output to DEVNULL to keep console clean (or we could log it)
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"RESTART COMMAND SENT FOR {name} (Background)", Fore.GREEN)
        time.sleep(5) # Wait for it to spin up

def check_status():
    all_good = True
    print("-" * 50)
    for name, url in URLS.items():
        try:
            # Short timeout because if it hangs, it's bad
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

def main():
    print(f"{Fore.YELLOW}=== CONNECTION GUARD ACTIVE ==={Style.RESET_ALL}")
    print("Monitoring public tunnel URLs every 30 seconds...")
    
    while True:
        check_status()
        time.sleep(30)

if __name__ == "__main__":
    main()
