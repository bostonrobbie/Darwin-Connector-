from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os
import json
import logging
import asyncio
import threading
import time
import datetime
from concurrent.futures import Future

# FIX: multiple event loops issue with ib_async/eventkit
# This must run before imports that might check for a loop
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

# Add parent dir to path to find client
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.ibkr.client import IBKRClient
from src.ibkr.rest_client import IBKRWebClient

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [IBKR] %(message)s')
logger = logging.getLogger("IBKR_Bridge")

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

config = load_config()
app = Flask(__name__)
CORS(app)

# Bridge State
STATE = {
    "last_trade": "None",
    "connected": False
}

# --- ASYNCIO BACKGROUND THREAD ---
# We create a specific loop for IBKR to run deeply in
ibkr_loop = asyncio.new_event_loop()

# Client holder
client = None
client_ready = threading.Event()

def start_loop(loop):
    asyncio.set_event_loop(loop)
    logger.info("Starting AsyncIO Event Loop...")
    
    # Instantiate Client INSIDE the thread so IB() picks up this loop
    global client
    try:
        # Client Factory Logic
        mode = config['ibkr'].get('tws_login_mode', 'manual')
        api_key = config['ibkr'].get('api_key', '')
        
        if mode == 'manual' and api_key:
             logger.info("Initializing IBKR Web Client (REST Mode)...")
             client = IBKRWebClient(config)
        else:
             logger.info("Initializing IBKR TWS Client (Socket Mode)...")
             client = IBKRClient(config)
             
        client_ready.set()
        logger.info("IBKR Client Initialized.")
        
        # Initial Connect
        logger.info("Initiating Background Connection...")
        loop.create_task(client.connect())
        
        loop.run_forever()
    except Exception as e:
        logger.error(f"Critical Loop Error: {e}")

# Start background thread
t = threading.Thread(target=start_loop, args=(ibkr_loop,), daemon=True)
t.start()

# Helper to run async tasks from Flask
def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, ibkr_loop).result()

@app.route('/health', methods=['GET'])
def health():
    if not client_ready.is_set():
        return jsonify({"status": "starting", "last_trade": STATE["last_trade"]})

    # Auto-Connect if disconnected
    if not client.is_connected():
        try:
            logger.info("Health Check: Attempting TWS Connection (Async)...")
            asyncio.run_coroutine_threadsafe(client.connect(), ibkr_loop)
        except Exception as e:
            logger.error(f"Auto-Connect Failed: {e}")

    connected = client.is_connected()
    STATE["connected"] = connected
    return jsonify({"status": "connected" if connected else "disconnected", "last_trade": STATE["last_trade"]})

@app.route('/webhook', methods=['POST'])
def webhook():
    if not client_ready.is_set():
        return jsonify({"error": "Bridge Starting"}), 503

    data = request.json
    if not data: return jsonify({"error": "No data"}), 400
    
    # Security
    secret = config['security']['webhook_secret']
    if data.get('secret') != secret:
        logger.warning(f"Unauthorized: {request.remote_addr}")
        return jsonify({"error": "Unauthorized"}), 401

    logger.info(f"Webhook: {data.get('action')} {data.get('symbol')}")
    
    # Execute on Background Loop
    try:
        start_time = time.time()
        # Blocks Flask thread until result is available
        result = run_async(client.execute_trade(data))
        duration = (time.time() - start_time) * 1000 # ms
        
        STATE["last_trade"] = f"{data.get('action')} {data.get('symbol')}"
        
        # Analytics Log
        with open('logs/analytics.csv', 'a') as f:
            # Timestamp, Platform, Symbol, Action, Duration_ms, Status
            ts = datetime.datetime.now().isoformat()
            f.write(f"{ts},IBKR,{data.get('symbol')},{data.get('action')},{duration:.2f},{result.get('status','error')}\n")
            
        return jsonify(result)
    except Exception as e:
        logger.error(f"Trade Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = config['server']['ibkr_port']
    logger.info(f"Starting IBKR Bridge on {port}")
    # Run Flask (blocks main thread)
    app.run(host="0.0.0.0", port=port)
