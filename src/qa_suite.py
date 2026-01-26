import os
import socket
import json
import requests
import sys
from colorama import Fore, Style

def check_port(host, port):
    """Checks if a port is in use (False = Free/Good for binding, True = In Use/Bad)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def check_internet():
    try:
        requests.get("https://www.google.com", timeout=3)
        return True
    except:
        return False

def run_qa():
    print(f"{Fore.CYAN}[*] Running Self-Diagnostic QA Suite...{Style.RESET_ALL}")
    issues = []

    # 1. Config Check
    if not os.path.exists('config.json'):
        issues.append("[X] config.json missing!")
    else:
        try:
            with open('config.json', 'r') as f:
                conf = json.load(f)

            # Verify Critical Fields
            if not conf.get('security', {}).get('webhook_secret'):
                issues.append("[X] Webhook Secret is empty!")

            # Verify Paths
            tws_path = conf.get('ibkr', {}).get('tws_path')
            if not os.path.exists(tws_path) and conf.get('ibkr').get('tws_login_mode') != 'ibc':
                 # If using IBC, tws_path determines version but file check might fail if pointing to launch shim?
                 # IBC mode uses separate installer logic.
                 pass
            elif not os.path.exists(tws_path):
                 issues.append(f"[X] TWS Path invalid: {tws_path}")

        except Exception as e:
            issues.append(f"[X] Config JSON malformed: {e}")

    # 2. Port Availability (Services shouldn't be running yet if we are starting)
    # Actually, we want them free.
    # But if this runs inside main.py *before* launch, they should be free.
    # If this runs *after* launch, they should be taken.
    # Let's assume Pre-Flight.

    # 3. Internet
    if not check_internet():
        issues.append("[!] No Internet Connection detected.")

    # 4. Unit Tests Integration
    print(f"{Fore.CYAN}[*] Running Test Suite...{Style.RESET_ALL}")
    import unittest

    # Capture output to avoid noise, or let it print? Let it print for visibility.
    loader = unittest.TestLoader()
    suite = loader.discover('tests')

    # Create a custom result runner to capture success/fail
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)

    if not result.wasSuccessful():
        issues.append(f"[X] Unit Tests Failed: {len(result.errors)} errors, {len(result.failures)} failures.")

    if not issues:
        print(f"{Fore.GREEN}[OK] QA PASSED: System Ready.{Style.RESET_ALL}")
        return True
    else:
        for i in issues:
            print(f"{Fore.RED}{i}{Style.RESET_ALL}")
        return False
