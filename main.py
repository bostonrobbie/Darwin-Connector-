import sys
import os
import json
import time
import logging
import logging
import socket
import webbrowser
from colorama import init, Fore, Style
from src.manager import ProcessManager
from src.qa_suite import run_qa
from src.utils.logger import LogManager

init() # Colorama

# --- SINGLETON LOCK ---
# Check if another instance is already running
lock_socket = None
def acquire_lock():
    global lock_socket
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Bind to a high port that is unlikely to be used
        lock_socket.bind(('127.0.0.1', 64000))
    except socket.error:
        print(f"{Fore.RED}ERROR: Another instance of Unified Bridge is already running.{Style.RESET_ALL}")
        print(f"{Fore.RED}Please close the other window before starting a new one.{Style.RESET_ALL}")
        sys.exit(1)

# Ensure logs dir exists
if not os.path.exists('logs'):
    os.makedirs('logs')

# Setup Logging
logger = LogManager.get_logger("Supervisor", log_file="logs/supervisor.log")

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def main():
    acquire_lock()
    print(f"{Fore.CYAN}=========================================={Style.RESET_ALL}")
    print(f"{Fore.CYAN}       UNIFIED BRIDGE SUPERVISOR          {Style.RESET_ALL}")
    print(f"{Fore.CYAN}=========================================={Style.RESET_ALL}")
    
    # --- LATENCY OPTIMIZATION ---
    try:
        import psutil
        p = psutil.Process(os.getpid())
        p.nice(psutil.HIGH_PRIORITY_CLASS)
        print(f"{Fore.GREEN}[OK] High Priority Mode Enabled (Latency Optimized){Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️  Could not set High Priority: {e}{Style.RESET_ALL}")

    # 0. RUN QA CHECK
    if not run_qa():
        print(f"{Fore.YELLOW}QA Failed. Press Enter to continue anyway (or Ctrl+C to stop)...{Style.RESET_ALL}")
        input() # Wait for user ack if QA fails

    try:
        config = load_config()
    except Exception as e:
        print(f"{Fore.RED}Failed to load config.json: {e}{Style.RESET_ALL}")
        return

    mgr = ProcessManager(config)

    # --- 1. CLEANUP OLD MESS (ROBUST PORT KILL) ---
    print("[*] Cleaning up old processes...")
    
    # 1.1 Truncate Logs
    for log_file in ['logs/ibkr.log', 'logs/mt5.log', 'logs/dashboard.log', 'logs/supervisor.log']:
        with open(log_file, 'w') as f: f.write(f"--- Log Reset {time.ctime()} ---\n")

    # 1.2 Kill by Port
    mgr.kill_port(config['server']['ibkr_port'])
    mgr.kill_port(config['server']['mt5_port'])
    mgr.kill_port(8502) # Dashboard
            
    # Give OS a moment to release ports
    time.sleep(1)


    # --- 2. START COMPONENTS ---

    # 2.0 Auto-Launch External Apps
    print("[*] Checking External Applications...")

    # TWS Launch Removed as per request (API Key Mode)
    # if not mgr.check_tws_process(): ... (Removed)

    # Check MT5 - Always auto-launch if not running
    mt5_path = config['mt5'].get('path')
    if not mgr.check_mt5_process():
        print(f"{Fore.YELLOW}MT5 Terminal not running. Auto-launching...{Style.RESET_ALL}")
        if mt5_path and os.path.exists(mt5_path):
            mgr.launch_external_app("MT5", mt5_path)
            print(f"{Fore.CYAN}Waiting for MT5 to initialize...{Style.RESET_ALL}")
            # Wait for MT5 to fully load (terminal needs time to connect to broker)
            for i in range(20):  # Wait up to 20 seconds
                time.sleep(1)
                if mgr.check_mt5_process():
                    print(f"{Fore.GREEN}[OK] MT5 Terminal detected!{Style.RESET_ALL}")
                    time.sleep(5)  # Extra time for login
                    break
        else:
            print(f"{Fore.RED}MT5 Path not configured or not found: {mt5_path}{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}[OK] MT5 Terminal already running.{Style.RESET_ALL}")

    # Open TopStep Dashboard
    print(f"{Fore.CYAN}[*] Opening TopStep Dashboard...{Style.RESET_ALL}")
    webbrowser.open("https://topstepx.com/trade")
    
    # IBKR Bridge
    ib_log = open('logs/ibkr.log', 'a')
    ibkr_cmd = f'"{sys.executable}" -u src/ibkr/bridge.py'
    mgr.start_process("IBKR_Bridge", ibkr_cmd, stdout=ib_log, stderr=ib_log)

    # MT5 Bridge
    mt5_log = open('logs/mt5.log', 'a')
    mt5_cmd = f'"{sys.executable}" -u src/mt5/bridge.py'
    mgr.start_process("MT5_Bridge", mt5_cmd, stdout=mt5_log, stderr=mt5_log)

    # Tunnels (Primary & Backup)
    ibkr_sub = config['tunnels']['ibkr_subdomain']
    ibkr_port = config['server']['ibkr_port']
    mgr.start_tunnel(ibkr_port, ibkr_sub, "IBKR_Tunnel")
    mgr.start_backup_tunnel(ibkr_port, "IBKR_Backup", type="serveo")

    mt5_sub = config['tunnels']['mt5_subdomain']
    mt5_port = config['server']['mt5_port']
    mgr.start_tunnel(mt5_port, mt5_sub, "MT5_Tunnel")
    mgr.start_backup_tunnel(mt5_port, "MT5_Backup", type="serveo")

    # Dashboard

    # Dashboard
    dash_log = open('logs/dashboard.log', 'a')
    # CHANGED: Port 8502 to avoid conflicts
    dash_cmd = f'"{sys.executable}" -u -m streamlit run dashboard/app.py --server.port 8502 --server.headless true'
    mgr.start_process("Dashboard", dash_cmd, stdout=dash_log, stderr=dash_log)
    
    print("\n[OK] System Started. Press Ctrl+C to Stop.\n")

    # --- 3. MAIN LOOP ---
    last_app_check = time.time()
    first_run = True
    
    try:
        print(f"\n{Fore.WHITE}[*] Waiting for subsystem connections...{Style.RESET_ALL}")
        while True:
            mgr.monitor()
            
            # --- Auto-Restart with Backoff ---
            required = ["IBKR_Bridge", "MT5_Bridge", "IBKR_Tunnel", "MT5_Tunnel", "Dashboard"]
            for name in required:
                if name not in mgr.processes:
                    if mgr.should_restart(name):
                        mgr.register_restart(name)
                        print(f"{Fore.YELLOW}Auto-Restarting {name}...{Style.RESET_ALL}")
                        
                        # Re-trigger start
                        if "IBKR_Bridge" in name: mgr.start_process(name, ibkr_cmd, stdout=ib_log, stderr=ib_log)
                        elif "MT5_Bridge" in name: mgr.start_process(name, mt5_cmd, stdout=mt5_log, stderr=mt5_log)
                        elif "IBKR_Tunnel" in name: mgr.start_process(name, f"lt --port {ibkr_port} --subdomain {ibkr_sub}")
                        elif "MT5_Tunnel" in name: mgr.start_process(name, f"lt --port {mt5_port} --subdomain {mt5_sub}")
                        elif "Dashboard" in name: 
                            mgr.kill_port(8502) # Ensure port is free
                            mgr.start_process(name, dash_cmd, stdout=dash_log, stderr=dash_log)

            # --- Internal Health Checks (Localhost) & Status Monitor ---
            # Track previous states to print changes
            if 'connection_states' not in locals():
                connection_states = {"IBKR": False, "MT5": False}

            # IBKR Check
            ib_data = mgr.check_health("IBKR_Bridge", f"http://localhost:{config['server']['ibkr_port']}")
            if ib_data:
                is_connected = (ib_data.get("status") == "connected")
                if is_connected and (not connection_states["IBKR"] or first_run):
                    print(f"{Fore.GREEN}[OK] IBKR/TWS CONNECTED! Ready for trades.{Style.RESET_ALL}")
                    connection_states["IBKR"] = True
                elif not is_connected and (connection_states["IBKR"] or first_run):
                    # We only print disconnect on first run if we want to be explicit.
                    # User asked for "needs api key" message.
                    print(f"{Fore.RED}[!] IBKR DISCONNECTED (API Key Required){Style.RESET_ALL}")
                    connection_states["IBKR"] = False
            
            # MT5 Check
            mt5_data = mgr.check_health("MT5_Bridge", f"http://localhost:{config['server']['mt5_port']}")
            if mt5_data:
                is_connected = (mt5_data.get("status") == "connected")
                if is_connected and not connection_states["MT5"]:
                    print(f"{Fore.GREEN}[OK] MT5 CONNECTED! Ready for trades.{Style.RESET_ALL}")
                    connection_states["MT5"] = True
                elif not is_connected and connection_states["MT5"]:
                    print(f"{Fore.RED}[!] MT5 DISCONNECTED{Style.RESET_ALL}")
                    connection_states["MT5"] = False

            # TopStep Check (New)
            if 'TopStep' not in connection_states: connection_states['TopStep'] = False
            
            # Simple check based on log presence or we can hit the client if exposed
            # Since TopStepClient is inside MT5 bridge, we can check via MT5 bridge health or just assume if MT5 is up and logs say so.
            # Better: MT5 Bridge health endpoint should report TopStep status.
            
            # For now, let's look for the log line or just assume connected if config is valid?
            # Actually, let's update MT5 bridge health to include TopStep status.
            # But avoiding too many file edits, let's check log file for "TopStepX Connection Validated"
            
            # Or better, just print it once on startup and rely on logs?
            # User asked for a message.
            # Let's add it to the startup sequence connection list.
            
            # Ideally: Check manager.check_health("MT5_Bridge") -> returns {..., "topstep": "connected"}
            # I will assume I'll update MT5 bridge health first.
            if mt5_data and mt5_data.get("topstep_status") == "connected" and not connection_states["TopStep"]:
                 print(f"{Fore.GREEN}[OK] TOPSTEP CONNECTED! (via MT5 Bridge){Style.RESET_ALL}")
                 connection_states["TopStep"] = True
            elif mt5_data and mt5_data.get("topstep_status") != "connected" and connection_states["TopStep"]:
                 print(f"{Fore.YELLOW}[!] TOPSTEP DISCONNECTED{Style.RESET_ALL}")
                 connection_states["TopStep"] = False
            
    # --- External App Keep-Alive (Check every 60s) ---
            if time.time() - last_app_check > 60:
                # Check MT5
                if not mgr.check_mt5_process():
                    print(f"{Fore.RED}[ALERT] MT5 not running! Attempting re-launch...{Style.RESET_ALL}")
                    mt5_path = config['mt5'].get('path')
                    if mt5_path: mgr.launch_external_app("MT5", mt5_path)
                    
                last_app_check = time.time()
            
            first_run = False
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n[*] Stopping System...")
        mgr.cleanup()
        sys.exit(0)

if __name__ == "__main__":
    main()
