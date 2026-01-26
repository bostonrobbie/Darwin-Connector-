
import MetaTrader5 as mt5
import json
import os
import sys

# Add parent dir to path to find config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_config():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.json') # Adjust path if needed
    # Determine the correct path to config.json
    # Logic: tests/verify... -> ../(Unified_Bridge)/config.json
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'config.json')
    
    print(f"Loading config from: {config_path}")
    with open(config_path, 'r') as f:
        return json.load(f)

def test_connection():
    config = load_config()
    mt5_conf = config['mt5']
    
    print(f"Initializing MT5 connection check...")
    print(f"Path: {mt5_conf['path']}")
    print(f"Server: {mt5_conf['server']}")
    print(f"Login: {mt5_conf['login']}")
    
    if not mt5.initialize(path=mt5_conf['path']):
        print(f"FAILED to initialize MT5: {mt5.last_error()}")
        return False

    is_connected = mt5.login(
        login=int(mt5_conf['login']), 
        password=mt5_conf['password'], 
        server=mt5_conf['server']
    )
    
    if is_connected:
        print(f"SUCCESS: Connected to {mt5_conf['server']}")
        print(f"Account Info: {mt5.account_info()}")
        print(f"Terminal Info: {mt5.terminal_info()}")
    else:
        print(f"FAILED to login: {mt5.last_error()}")
        
    mt5.shutdown()
    return is_connected

if __name__ == "__main__":
    if test_connection():
        print("\n✅ Verification PASSED")
        sys.exit(0)
    else:
        print("\n❌ Verification FAILED")
        sys.exit(1)
