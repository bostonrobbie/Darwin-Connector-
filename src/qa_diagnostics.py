import os
import json
import requests
import sys

def check_file(path, name):
    if os.path.exists(path):
        print(f"[PASS] {name} found at {path}")
        return True
    else:
        print(f"[FAIL] {name} NOT found at {path}")
        return False

def check_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'settings.json')
    if check_file(config_path, "Settings JSON"):
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
                print(f"[PASS] Config loaded. Port: {data.get('ibkr', {}).get('port')}")
        except Exception as e:
            print(f"[FAIL] Config invalid: {e}")

def check_server_health():
    url = "http://127.0.0.1:5001/status"
    try:
        print(f"[*] Pinging Bridge Server at {url}...")
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            state = data.get("state", {})
            print(f"[PASS] Server is UP.")
            print(f"       - IBKR Connected: {state.get('ibkr_connected')}")
            print(f"       - Last Trade: {state.get('last_trade')}")
            print(f"       - Uptime Start: {state.get('uptime_start')}")
        else:
            print(f"[FAIL] Server returned status code {resp.status_code}")
    except Exception as e:
        print(f"[WARN] Server not reachable (Is it running?): {e}")

if __name__ == "__main__":
    print("=== IBKR BRIDGE QA DIAGNOSTICS ===")
    check_config()
    check_file("bridge.log", "Log File")
    check_server_health()
    print("==================================")
    print("Run this script while the bridge is running to verify connectivity.")
