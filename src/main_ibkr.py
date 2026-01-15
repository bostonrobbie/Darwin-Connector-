import sys
import os
import signal
import asyncio
import logging

# Ensure src in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- LOGGING SETUP ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(BASE_DIR, "bridge.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)

import ib_executor
import webhook_listener

def main():
    print("=========================================")
    print("   TradingView to IBKR Bridge (Async)    ")
    print("=========================================")
    
    # Attempt initial connection in background loop usually, 
    # but here we rely on the webhook triggering it or pre-connect.
    # Since Flask is blocking, we need to run Flask. 
    # The 'ib_executor' handles the asyncio loop usage via ib.run() wrapper.
    
    # Note: ib_insync/async typically wants to run the loop. 
    # We will use the Webhook listener's Flask runner which is sync, 
    # and use ib.run() to invoke async commands.
    
    # Start Reconnection Thread (Background)
    # This enables "Launch First, Login Later" workflow
    import threading
    import time

    def connection_monitor():
        while True:
            if not ib_executor.ib.isConnected():
                print("[MONITOR] IBKR Disconnected. Retrying in 5 seconds...")
                try:
                    # Async call inside sync thread requires ib.run logic
                    ib_executor.ib.run(ib_executor.connect_ib())
                except Exception as e:
                    print(f"[MONITOR] Connection attempt failed: {e}")
            else:
                # If connected, just sleep longer
                pass
            
            time.sleep(10)

    monitor_thread = threading.Thread(target=connection_monitor, daemon=True)
    monitor_thread.start()

    try:
        webhook_listener.start_server()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
    finally:
        ib_executor.disconnect()

if __name__ == "__main__":
    main()
