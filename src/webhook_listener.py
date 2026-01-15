from flask import Flask, request, jsonify
from flask_cors import CORS
import ib_executor
import logging
import os
import datetime

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(BASE_DIR, "bridge.log")

# Setup logging (File + Console)
# Logging is configured in main_ibkr.py
logger = logging.getLogger("Webhook")

# --- GLOBAL STATE ---
BRIDGE_STATE = {
    "ibkr_connected": False,
    "last_trade": "None",
    "uptime_start": str(datetime.datetime.now())
}

app = Flask(__name__)
CORS(app) # Enable CORS for Dashboard

SETTINGS = ib_executor.SETTINGS
SECURITY_CONFIG = SETTINGS.get('security', {})
SERVER_CONFIG = SETTINGS.get('server', {})

def read_logs(lines=15):
    """Reads the last N lines from the log file."""
    if not os.path.exists(LOG_PATH):
        return ["Log file not found."]
    try:
        with open(LOG_PATH, 'r') as f:
            return f.readlines()[-lines:]
    except Exception as e:
        return [f"Error reading logs: {str(e)}"]

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data"}), 400

    # Security Check
    incoming_secret = data.get('secret')
    configured_secret = SECURITY_CONFIG.get('webhook_secret')
    if configured_secret and incoming_secret != configured_secret:
        logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    logger.info(f"Received Webhook: {data.get('action')} {data.get('symbol')}")

    try:
        result = ib_executor.execute_trade_sync_wrapper(data)
        
        # Update State
        BRIDGE_STATE["last_trade"] = f"{data.get('action')} {data.get('symbol')} @ {datetime.datetime.now().strftime('%H:%M:%S')}"
        
        logger.info(f"Execution Result: {result}")
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Execution Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Simple Health Check."""
    is_connected = ib_executor.check_health_sync()
    return jsonify({"status": "connected" if is_connected else "disconnected"}), 200 if is_connected else 503

@app.route('/status', methods=['GET'])
def status():
    """Full Status Endpoint for Dashboard."""
    # Ping IBKR
    connected = ib_executor.check_health_sync()
    BRIDGE_STATE["ibkr_connected"] = connected
    
    return jsonify({
        "state": BRIDGE_STATE,
        "logs": read_logs(20)
    })

def start_server():
    host = SERVER_CONFIG.get('host', '0.0.0.0')
    port = SERVER_CONFIG.get('port', 5001) 
    debug = SERVER_CONFIG.get('debug', False)
    
    logger.info(f"Starting IBKR Bridge Server on {host}:{port}")
    app.run(host=host, port=port, debug=debug)
