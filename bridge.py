import MetaTrader5 as mt5
import json
import os
import sys
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS

# --- CONFIGURATION ---
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')

# --- LOGGING SETUP ---
import logging
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "bridge.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5_Bridge")

# --- GLOBAL STATE ---
BRIDGE_STATE = {
    "mt5_connected": False,
    "last_trade": "None",
    "uptime_start": None
}
import datetime
BRIDGE_STATE["uptime_start"] = str(datetime.datetime.now())

def load_config():
    if not os.path.exists(CONFIG_PATH):
        logging.critical(f"settings.json not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

CONFIG = load_config()

# --- MT5 MANAGEMENT ---
def initialize_mt5():
    path = CONFIG['mt5']['path']
    login = int(CONFIG['mt5']['login'])
    password = CONFIG['mt5']['password']
    server = CONFIG['mt5']['server']

    logging.info(f"Connecting to {server} as {login}...")
    
    if not mt5.initialize():
        logging.warning(f"Failed to attach: {mt5.last_error()}. Trying explicit path...")
        # Attempt 2: Launch
        if not mt5.initialize(path=path):
            logging.error(f"Failed to launch MT5: {mt5.last_error()}")
            return False
            
    # Login Check
    if not mt5.login(login=login, password=password, server=server):
        logging.error(f"Login failed: {mt5.last_error()}")
        return False
        
    logging.info("MT5 Connected & Logged In.")
    BRIDGE_STATE["mt5_connected"] = True
    return True

# --- TRADING LOGIC ---
def close_positions(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return {"status": "success", "message": f"No positions to close for {symbol}"}

    count = 0
    for pos in positions:
        # Close by Opposite Deal
        tick = mt5.symbol_info_tick(symbol)
        if pos.type == mt5.ORDER_TYPE_BUY:
            type_order = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            type_order = mt5.ORDER_TYPE_BUY
            price = tick.ask
            
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": type_order,
            "position": pos.ticket,
            "price": price,
            "deviation": 20,
            "magic": CONFIG['trading']['magic_number'],
            "comment": "Close-TV-Bridge",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            count += 1
            
    return {"status": "success", "message": f"Closed {count} positions for {symbol}"}

def execute_trade(data):
    # 1. Symbol Mapping
    symbol_in = data.get('symbol', '').upper()
    map_conf = CONFIG['trading']['symbol_map'].get(symbol_in)
    
    symbol_out = symbol_in
    multiplier = 1.0
    
    if map_conf:
        if isinstance(map_conf, dict):
            symbol_out = map_conf['name']
            multiplier = map_conf.get('multiplier', 1.0)
        else:
            symbol_out = map_conf
            
    logging.info(f"Trade Request: {symbol_in} -> {symbol_out} (x{multiplier})")
    
    # 2. Check Action
    action = data.get('action', '').upper()
    
    # 2a. Handle Exits/Flattening
    if action in ['CLOSE', 'EXIT', 'FLATTEN']:
        return close_positions(symbol_out)
        
    # 3. Volume Calculation
    try:
        raw_qty = float(data.get('volume', 0))
    except:
        raw_qty = CONFIG['trading']['default_volume']
        
    final_vol = raw_qty * multiplier
    
    # Validate against Symbol Info
    s_info = mt5.symbol_info(symbol_out)
    if not s_info:
        return {"status": "error", "message": f"Symbol {symbol_out} not found in Market Watch!"}
        
    if final_vol < s_info.volume_min:
        final_vol = s_info.volume_min
    
    # Rounding to nearest step
    if s_info.volume_step > 0:
        steps = round(final_vol / s_info.volume_step)
        final_vol = steps * s_info.volume_step
        final_vol = round(final_vol, 2)
        
    # 4. Execute
    tick = mt5.symbol_info_tick(symbol_out)
    if not tick:
         return {"status": "error", "message": f"No price data (tick) for {symbol_out}"}

    # Order Type & Price Logic
    order_type_str = data.get('type', 'MARKET').upper()
    limit_price = float(data.get('price', 0.0))
    
    if order_type_str == 'LIMIT' and limit_price > 0:
        action_type = mt5.TRADE_ACTION_PENDING
        price = limit_price
        if action == 'BUY':
            order_type = mt5.ORDER_TYPE_BUY_LIMIT
        elif action == 'SELL':
            order_type = mt5.ORDER_TYPE_SELL_LIMIT
        else:
             return {"status": "error", "message": f"Unknown action: {action}"}
    else:
        # Market Execution (Default)
        action_type = mt5.TRADE_ACTION_DEAL
        if action == 'BUY':
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        elif action == 'SELL':
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}
        
    req = {
        "action": action_type,
        "symbol": symbol_out,
        "volume": final_vol,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": CONFIG['trading']['magic_number'],
        "comment": "Antigravity-Bridge",
        "type_time": mt5.ORDER_TIME_GTC, # Good till cancelled
        "type_filling": mt5.ORDER_FILLING_IOC if action_type == mt5.TRADE_ACTION_DEAL else mt5.ORDER_FILLING_RETURN,
    }
    
    result = mt5.order_send(req)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"status": "error", "message": f"MT5 Error: {result.comment} ({result.retcode})"}
        
    return {"status": "success", "order": result.order, "volume": result.volume}
    
def read_logs(lines=10):
    if not os.path.exists(LOG_PATH):
        return ["Log file not found."]
    try:
        with open(LOG_PATH, 'r') as f:
            return f.readlines()[-lines:]
    except:
        return ["Error reading logs."]

# --- WEB SEVER ---
app = Flask(__name__)
CORS(app)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    logging.info(f"Received Payload: {json.dumps(data)}")
    
    # Security check (basic)
    if data.get('secret') != CONFIG['security']['webhook_secret']:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
        
    res = execute_trade(data)
    BRIDGE_STATE["last_trade"] = f"{data.get('action')} {data.get('symbol')} @ {datetime.datetime.now().strftime('%H:%M:%S')}"
    logging.info(f"RESULT: {res}")
    return jsonify(res)

@app.route('/status', methods=['GET'])
def status():
    # Ping MT5 to be sure
    connected = mt5.terminal_info() is not None
    BRIDGE_STATE["mt5_connected"] = connected
    
    return jsonify({
        "state": BRIDGE_STATE,
        "logs": read_logs(15)
    })

if __name__ == "__main__":
    print("===================================")
    print("   NEW CLEAN BRIDGE STARTED        ")
    print("===================================")
    logging.info("BRIDGE STARTED")
    
    if not initialize_mt5():
        logging.warning("Running in Offline/Debug mode (MT5 not connected)")
    
    # Start Flask
    app.run(host=CONFIG['server']['host'], port=CONFIG['server']['port'])
