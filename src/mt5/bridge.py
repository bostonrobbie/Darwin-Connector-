import MetaTrader5 as mt5
import json
import os
import sys
import logging
import datetime
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import concurrent.futures
from waitress import serve

# Add parent dir to path to find client
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.topstep.client import TopStepClient
from src.utils.alerts import AlertManager
from src.utils.database import DatabaseManager
from src.utils.logger import LogManager
from src.utils.scheduler import TradingScheduler, WebhookValidator, is_broker_paused

# Logging
logger = LogManager.get_logger("MT5_Bridge", log_file="logs/mt5.log")

def load_config():
    # Load from parent dir
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.json')
    with open(path, 'r') as f:
        return json.load(f)

CONFIG = load_config()
MT5_CONF = CONFIG['mt5']

# Initialize TopStep Client
ts_client = TopStepClient(CONFIG)
# Initialize Utils
alerts = AlertManager(CONFIG)
db = DatabaseManager('trades.db')
webhook_validator = WebhookValidator(CONFIG)

# Global Executor for Parallel Tasks
executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

# Config file path for live updates
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.json')

def reload_config():
    """Reload config from disk for live settings updates."""
    global CONFIG
    try:
        with open(CONFIG_PATH, 'r') as f:
            CONFIG = json.load(f)
        return CONFIG
    except Exception as e:
        logger.error(f"Failed to reload config: {e}")
        return CONFIG

# Non-blocking validation on startup
try:
    ts_client.validate_connection()
except Exception as e:
    logger.error(f"TopStep Setup Error: {e}")

# Log Eval Mode Status
eval_mode_status = CONFIG.get('topstep', {}).get('eval_mode', False)
logger.info(f"TopStep Eval Mode: {'ENABLED (1 Mini)' if eval_mode_status else 'DISABLED (Funded/7 Micros)'}")

# Global State
STATE = {
    "connected": False,
    "connected": False,
    "last_trade": "None"
}

# Optimization: Symbol Cache to avoid IPC calls for static data (Point, Digits)
SYMBOL_CACHE = {}

def warm_cache(symbols):
    """Pre-loads symbol info into cache."""
    for s in symbols:
        info = mt5.symbol_info(s)
        if info:
            SYMBOL_CACHE[s] = info
            logger.info(f"Cached Info for {s}: Point={info.point}")
        else:
            logger.warning(f"Failed to cache {s}")

def initialize_mt5():
    """Connects to MT5 terminal."""
    try:
        if not mt5.initialize(path=MT5_CONF['path']):
            logger.error(f"Failed to init MT5: {mt5.last_error()}")
            return False
            
        # Login
        if not mt5.login(
            login=int(MT5_CONF['login']), 
            password=MT5_CONF['password'], 
            server=MT5_CONF['server']
        ):
            logger.error(f"MT5 Login failed: {mt5.last_error()}")
            return False
            
        STATE["connected"] = True
        logger.info(f"Connected to MT5: {MT5_CONF['server']}")
        
        # Warm Cache
        common_symbols = ["NQ", "MNQ", "ES", "MES", "NQ_H", "ES_H"]
        warm_cache(common_symbols)
        
        return True
    except Exception as e:
        logger.error(f"Init Error: {e}")
        return False

def validate_terminal_state():
    """Checks if MT5 is connected and ready before trading."""
    if not mt5.terminal_info():
        logger.warning("MT5 Terminal Info failed. Attempting Reconnect...")
        return initialize_mt5()
    return True

def safe_order_send(request, max_retries=3):
    """Wraps order_send with retry logic for transient errors."""
    for i in range(max_retries):
        try:
            res = mt5.order_send(request)
            if res is None:
                logger.error(f"Order Send returned None (Attempt {i+1})")
                time.sleep(0.5)
                continue
                
            if res.retcode == mt5.TRADE_RETCODE_DONE:
                return res
            elif res.retcode in [mt5.TRADE_RETCODE_TIMEOUT, mt5.TRADE_RETCODE_CONNECTION]:
                logger.warning(f"Transient Error {res.retcode}: {res.comment}. Retrying...")
                time.sleep(1.0)
            else:
                # Fatal error (e.g. Invalid Volume)
                logger.error(f"Fatal Order Error {res.retcode}: {res.comment}")
                return res
        except Exception as e:
            logger.error(f"Exception during order send: {e}")
            time.sleep(0.5)
            
    return None

def close_positions(symbol, raw_symbol=None):
    """
    Closes all positions for a given symbol, using fuzzy matching to handle
    broker suffix mismatches (e.g. NQ1! vs NQ_H).
    """
    # Build robust search set
    search_symbols = {symbol}
    if raw_symbol:
        search_symbols.add(raw_symbol)
        clean = raw_symbol.replace('1!', '').replace('2!', '')
        search_symbols.add(clean)
        search_symbols.add(clean + "_H")
        
    logger.info(f"Closing Positions for {symbol}. Scanning for: {search_symbols}")

    all_positions = mt5.positions_get()
    if not all_positions:
        return {"status": "success", "message": "No open positions to close."}

    # Filter positions
    target_positions = [p for p in all_positions if p.symbol in search_symbols]
    
    if not target_positions:
        return {"status": "success", "message": f"No positions found matching {search_symbols}"}

    count = 0
    for pos in target_positions:
        tick = mt5.symbol_info_tick(pos.symbol) # Use the ACTUAL symbol of the position
        if not tick: 
            logger.warning(f"No tick for {pos.symbol}, skipping close.")
            continue
        
        type_order = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
        
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol, # Use exact position symbol
            "volume": pos.volume,
            "type": type_order,
            "position": pos.ticket, # CRITICAL: Close by Ticket
            "price": price,
            "magic": MT5_CONF.get('magic_number', 0),
            "comment": "Unified-Bridge-Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            count += 1
            logger.info(f"Closed position {pos.ticket} ({pos.symbol})")
        else:
            logger.error(f"Failed to close {pos.ticket}: {res.comment}")
            
    return {"status": "success", "closed": count}

def calculate_equity_volume(equity_pct, symbol):
    """
    Calculate position size based on equity percentage.
    equity_pct: Percentage of equity to risk (e.g., 2.0 = 2%)
    Returns: volume (lot size)
    """
    try:
        account_info = mt5.account_info()
        if not account_info:
            logger.error("Cannot get account info for equity sizing")
            return 1.0  # Fallback to 1 lot

        equity = account_info.equity
        balance = account_info.balance

        # Get symbol info for contract value
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            logger.error(f"Cannot get symbol info for {symbol}")
            return 1.0

        # Calculate risk amount
        risk_amount = equity * (equity_pct / 100.0)

        # Get contract specifications
        # For futures: contract_size * price = notional value
        # For forex: lot size * price = notional value
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return 1.0

        current_price = tick.ask
        contract_size = sym_info.trade_contract_size if hasattr(sym_info, 'trade_contract_size') else 1.0

        # Calculate volume based on margin requirement approach
        # margin_rate gives us the leverage essentially
        margin_initial = sym_info.margin_initial if hasattr(sym_info, 'margin_initial') and sym_info.margin_initial > 0 else 1000

        # Volume = Risk Amount / Margin per lot
        if margin_initial > 0:
            volume = risk_amount / margin_initial
        else:
            # Fallback: Use 1% of equity per lot as rough estimate
            volume = risk_amount / (current_price * contract_size * 0.01)

        # Apply min/max volume constraints
        min_vol = sym_info.volume_min if hasattr(sym_info, 'volume_min') else 0.01
        max_vol = sym_info.volume_max if hasattr(sym_info, 'volume_max') else 100.0
        vol_step = sym_info.volume_step if hasattr(sym_info, 'volume_step') else 0.01

        # Round to volume step
        volume = max(min_vol, min(max_vol, volume))
        volume = round(volume / vol_step) * vol_step
        volume = round(volume, 2)

        logger.info(f"Equity Sizing: {equity_pct}% of ${equity:.2f} = ${risk_amount:.2f} -> {volume} lots")
        return volume

    except Exception as e:
        logger.error(f"Equity calculation error: {e}")
        return 1.0  # Safe fallback

def execute_trade(data):
    # 1. Map Symbol
    raw = data.get('symbol', '').upper()
    mapping = MT5_CONF.get('symbol_map', {}).get(raw)

    symbol = raw
    mult = 1.0

    if mapping:
        if isinstance(mapping, dict):
            symbol = mapping['name']
            mult = mapping['multiplier']
        else:
            symbol = mapping

    logger.info(f"Trade: {data.get('action')} {raw} -> {symbol} (x{mult})")

    # Force uppercase for safety
    symbol = symbol.upper()

    # 2. Action
    action = data.get('action', '').upper()
    if action in ['CLOSE', 'EXIT', 'FLATTEN']:
        return close_positions(symbol, raw_symbol=raw)

    # 3. Volume - Support equity percentage OR fixed volume
    equity_pct = data.get('equity_pct', 0)

    # Check for default equity pct in config if not provided in webhook
    if not equity_pct or float(equity_pct) <= 0:
        default_equity = MT5_CONF.get('execution', {}).get('default_equity_pct', 0)
        if default_equity and float(default_equity) > 0:
            equity_pct = default_equity
            logger.info(f"Using default equity_pct from config: {equity_pct}%")

    if equity_pct and float(equity_pct) > 0:
        # Equity-based sizing
        vol = calculate_equity_volume(float(equity_pct), symbol) * mult
        logger.info(f"Using equity-based sizing: {equity_pct}% -> {vol} lots")
    else:
        # Fixed volume (default behavior)
        vol = float(data.get('volume', 1.0)) * mult
    # Round logic could go here (min volume check)
    
    # 4. Netting Logic (Simulate Netting on Hedging Account)
    # Check for opposite positions
    opposite_type = mt5.ORDER_TYPE_SELL if action == 'BUY' else mt5.ORDER_TYPE_BUY
    
    # 4.1 Get all positions to debug mismatch
    all_positions = mt5.positions_get()
    if all_positions:
        logger.info(f"Open Positions in MT5: {[p.symbol for p in all_positions]}")
    else:
        logger.info("No Open Positions in MT5.")

    # 4.2 specific symbol lookup (Try raw, mapped, and common variations)
    search_symbols = {symbol, raw, raw.replace('1!', ''), raw.replace('1!', '') + "_H"}
    positions = []
    
    # Filter all positions that match any of our search symbols
    if all_positions:
        for p in all_positions:
            if p.symbol in search_symbols:
                positions.append(p)
    
    if positions:
        for pos in positions:
            if pos.type == opposite_type:
                logger.info(f"Netting: Closing opposite position {pos.ticket} ({pos.volume})")
                
                # Close this position
                # Determine close price
                tick = mt5.symbol_info_tick(pos.symbol) # Use pos.symbol to be safe
                close_price = tick.ask if pos.type == mt5.ORDER_TYPE_SELL else tick.bid # Buy to close Sell (Ask), Sell to close Buy (Bid)
                
                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": pos.volume,
                    "type": mt5.ORDER_TYPE_BUY if pos.type == mt5.ORDER_TYPE_SELL else mt5.ORDER_TYPE_SELL,
                    "position": pos.ticket,
                    "price": close_price,
                    "magic": MT5_CONF.get('magic_number', 0),
                    "comment": "Unified-Bridge-Netting",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                res = mt5.order_send(req)
                if res.retcode != mt5.TRADE_RETCODE_DONE:
                    logger.error(f"Netting Fail: {res.comment}")
                else:
                    # Reduce incoming volume by closed volume
                    vol -= pos.volume
                    
    # 5. Order Setup (Remaining Volume)
    if vol <= 0.0001: # EPSILON check
        logger.info("Netting Completed. No remaining volume to open.")
        return {"success": True, "message": "Closed via Netting"}

    # 0. Pre-Trade Validation
    if not validate_terminal_state():
        return {"error": "MT5 Terminal Disconnected"}

    logger.info(f"Opening New Position: {action} {vol} {symbol}")
    
    # 5. Order Type & Price Logic
    tick = mt5.symbol_info_tick(symbol)
    if not tick: return {"error": f"No Price for {symbol}"}

    # Get Configs
    exec_conf = MT5_CONF.get('execution', {})
    order_type_config = exec_conf.get('default_type', 'MARKET').upper()
    slippage_ticks = exec_conf.get('slippage_offset_ticks', 2)

    # Optimization: Use Cache for Point
    info = SYMBOL_CACHE.get(symbol)
    if not info:
         info = mt5.symbol_info(symbol)
         if info: SYMBOL_CACHE[symbol] = info

    point = info.point if info else 0.0001
    digits = info.digits if info and hasattr(info, 'digits') else 2

    # Use MARKET order for immediate execution (more reliable)
    if order_type_config == 'MARKET':
        action_type = mt5.TRADE_ACTION_DEAL
        ot = mt5.ORDER_TYPE_BUY if action == 'BUY' else mt5.ORDER_TYPE_SELL
        # For market orders, use current ask/bid
        ex_price = tick.ask if action == 'BUY' else tick.bid
        filling_mode = mt5.ORDER_FILLING_IOC  # Immediate or Cancel for market orders
    else:
        # LIMIT order mode
        action_type = mt5.TRADE_ACTION_PENDING
        ot = mt5.ORDER_TYPE_BUY_LIMIT if action == 'BUY' else mt5.ORDER_TYPE_SELL_LIMIT
        # Get tick size for proper price rounding
        tick_size = info.trade_tick_size if info and hasattr(info, 'trade_tick_size') and info.trade_tick_size > 0 else point
        offset_val = tick_size * slippage_ticks

        requested_price = float(data.get('price', 0.0))
        if requested_price > 0:
            ex_price = requested_price
        else:
            # Marketable Limit: Ask + Offset (Buy), Bid - Offset (Sell)
            if action == 'BUY':
                 ex_price = tick.ask + offset_val
            else:
                 ex_price = tick.bid - offset_val

        # Round price to valid tick size
        if tick_size > 0:
            ex_price = round(ex_price / tick_size) * tick_size
            ex_price = round(ex_price, digits)
        filling_mode = mt5.ORDER_FILLING_RETURN
             
    # 7. TP/SL Calculation
    # User Request: NO Auto Defaults. Only if given.
    
    input_sl = float(data.get('sl', 0))
    input_tp = float(data.get('tp', 0))
    
    sl_price = 0.0
    tp_price = 0.0
    
    # Calculate SL
    if input_sl > 0:
        sl_price = input_sl
            
    # Calculate TP
    if input_tp > 0:
        tp_price = input_tp

    logger.info(f"Order Params: Price={ex_price:.5f}, SL={sl_price:.5f}, TP={tp_price:.5f}")

    req = {
        "action": action_type,
        "symbol": symbol,
        "volume": vol,
        "type": ot,
        "price": ex_price,
        "sl": sl_price,
        "tp": tp_price,
        "magic": MT5_CONF.get('magic_number', 0),
        "comment": "Unified-Bridge",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }
    
    # ... (Order Sending with Retry)
    try:
        res = safe_order_send(req)
    except Exception as e:
        logger.error(f"MT5 Order Send Exception: {e}")
        return {"error": f"MT5 Exception: {e}"}

    if res is None:
        return {"error": "MT5 order_send returned None after retries"}
        
    if res.retcode != mt5.TRADE_RETCODE_DONE:
        return {"error": f"MT5 Fail: {res.comment} ({res.retcode})"}
        
    # Calculate Slippage (Approximate since it's a Limit Order placed, fill might happen later)
    # But for Marketable Limit that fills instantly, res.price is the fill price of the DEAL?
    # No, for Pending Order, res.price is just the order price?
    # Actually for Marketable Limit that executes immediately, retcode is DONE_PARTIAL or DONE?
    # We will report the requested price.
    actual_price = res.price 
    if actual_price == 0: actual_price = ex_price # Pending order might not have fill price yet
    
    slippage = 0.0
    if ex_price > 0 and actual_price > 0:
        slippage = abs(actual_price - ex_price)

    return {
        "success": True, 
        "order": res.order, 
        "expected_price": ex_price, 
        "executed_price": actual_price, 
        "slippage": slippage
    }

# Flask
app = Flask(__name__)
CORS(app)

# Helper to forward to IBKR
def forward_to_ibkr(data):
    """Forwards the webhook payload to the IBKR bridge."""
    try:
        # Prepare URL
        ibkr_port = CONFIG['server'].get('ibkr_port', 5001)
        url = f"http://127.0.0.1:{ibkr_port}/webhook"
        
        # Clone data to avoid mutating original
        payload = data.copy()
        payload['secret'] = CONFIG['security']['webhook_secret']
        
        # Symbol Cleanup for IBKR
        # MT5 uses "MNQ1!", IBKR uses "MNQ" (usually continuous).
        # We strip digits and ! from the end if it looks like a TradingView ticker
        raw = payload.get('symbol', '').upper()
        if '1!' in raw:
            # Assume formatted like "MNQ1!" -> "MNQ"
            clean = raw.replace('1!', '').replace('2!', '')
            payload['symbol'] = clean
            payload['secType'] = 'FUT' # Force Future if it was a TV future ticker
            payload['exchange'] = 'GLOBEX' # Good default for US Futures
        
        # Send
        # We use a short timeout so MT5 doesn't hang waiting for IBKR
        try:
            requests.post(url, json=payload, timeout=0.5) 
        except requests.exceptions.ReadTimeout:
            pass # We don't care about response, just fire and forget roughly
        except Exception as e:
            logger.error(f"Forwarding Fail: {e}")
            
    except Exception as e:
        logger.error(f"Forwarding Error: {e}")

@app.route('/health', methods=['GET'])
def health():
    connected = mt5.terminal_info() is not None
    STATE['connected'] = connected

    # Check TopStep Status
    ts_connected = ts_client.connected

    # Reload config for current pause states
    current_config = reload_config()
    broker_controls = current_config.get('broker_controls', {})

    return jsonify({
        "status": "connected" if connected else "disconnected",
        "last_trade": STATE['last_trade'],
        "topstep_status": "connected" if ts_connected else "disconnected",
        "mt5_paused": broker_controls.get('mt5_paused', False),
        "ibkr_paused": broker_controls.get('ibkr_paused', False),
        "topstep_paused": broker_controls.get('topstep_paused', False)
    })

@app.route('/pause/<broker>', methods=['POST'])
def pause_broker(broker):
    """Pause or unpause a specific broker."""
    from src.utils.scheduler import set_broker_paused

    data = request.json or {}
    paused = data.get('paused', True)

    if broker.lower() not in ['mt5', 'ibkr', 'topstep']:
        return jsonify({"error": "Invalid broker"}), 400

    if set_broker_paused(CONFIG_PATH, broker, paused):
        status = "paused" if paused else "resumed"
        logger.info(f"Broker {broker.upper()} {status} by user")
        return jsonify({"status": "success", "broker": broker, "paused": paused})
    else:
        return jsonify({"error": "Failed to update broker state"}), 500

@app.route('/close_all', methods=['POST'])
def close_all_positions():
    """Close all positions on MT5 and optionally forward to other brokers."""
    data = request.json or {}

    # Validate secret if provided
    if data.get('secret') and data.get('secret') != CONFIG['security']['webhook_secret']:
        return jsonify({"error": "Unauthorized"}), 401

    platform = data.get('platform', 'all').lower()
    results = {}

    # Close MT5 positions
    if platform in ['all', 'mt5']:
        try:
            res = close_positions("", raw_symbol="")  # Close all
            results['mt5'] = res
            logger.info(f"Close All (MT5): {res}")
        except Exception as e:
            results['mt5'] = {"error": str(e)}

    # Close TopStep positions
    if platform in ['all', 'topstep']:
        try:
            ts_res = ts_client.execute_trade({"action": "CLOSE", "symbol": "MNQ"})
            results['topstep'] = ts_res
            logger.info(f"Close All (TopStep): {ts_res}")
        except Exception as e:
            results['topstep'] = {"error": str(e)}

    # Forward to IBKR
    if platform in ['all', 'ibkr']:
        try:
            forward_to_ibkr({"action": "CLOSE", "symbol": ""})
            results['ibkr'] = {"status": "forwarded"}
        except Exception as e:
            results['ibkr'] = {"error": str(e)}

    return jsonify({"status": "success", "results": results})

@app.route('/trades', methods=['GET'])
def get_trades():
    """Get trade log for verification."""
    limit = request.args.get('limit', 100, type=int)
    platform = request.args.get('platform', None)
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    trades = db.get_trades(limit=limit, platform=platform, start_date=start_date, end_date=end_date)
    return jsonify({"trades": trades, "count": len(trades)})

@app.route('/trades/summary', methods=['GET'])
def get_trade_summary():
    """Get trade summary statistics."""
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    summary = db.get_trade_summary(start_date=start_date, end_date=end_date)
    return jsonify({"summary": summary})

@app.route('/trades/export', methods=['GET'])
def export_trades():
    """Export trades to CSV."""
    import tempfile
    from flask import send_file

    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    filepath = os.path.join(tempfile.gettempdir(), f"trades_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    if db.export_trades_csv(filepath, start_date=start_date, end_date=end_date):
        return send_file(filepath, as_attachment=True, download_name="trades_export.csv")
    else:
        return jsonify({"error": "No trades to export"}), 404

@app.route('/webhook', methods=['POST'])
def webhook():
    webhook_received_at = datetime.datetime.now().isoformat()
    data = request.json
    raw_webhook = json.dumps(data)

    if data.get('secret') != CONFIG['security']['webhook_secret']:
         logger.warning(f"Unauthorized Webhook Attempt: {request.remote_addr}")
         return jsonify({"error": "Unauthorized"}), 401

    logger.info(f"Received Webhook: {raw_webhook}")

    # Reload config for live pause/settings updates
    current_config = reload_config()

    # Validate webhook (rogue trade protection)
    is_valid, rejection_reason = webhook_validator.validate_webhook(data)
    if not is_valid:
        logger.warning(f"REJECTED WEBHOOK: {rejection_reason}")
        db.log_trade(
            "REJECTED",
            data,
            "rejected",
            0,
            details=rejection_reason,
            webhook_received_at=webhook_received_at,
            raw_webhook=raw_webhook,
            rejected_reason=rejection_reason
        )
        return jsonify({"error": "Rejected", "reason": rejection_reason}), 400

    # 1. Forward to IBKR (Parallel - Fire & Forget) - Check if paused
    if not is_broker_paused(current_config, 'ibkr'):
        executor.submit(forward_to_ibkr, data)
    else:
        logger.info("IBKR is PAUSED - Skipping trade forwarding")

    # 2. Forward to TopStepX (Parallel) - Check if paused
    if not is_broker_paused(current_config, 'topstep'):
        executor.submit(handle_topstep_logic, data)
    else:
        logger.info("TopStep is PAUSED - Skipping trade")

    # 3. Execute MT5 (Main Thread - Critical Path) - Check if paused
    if is_broker_paused(current_config, 'mt5'):
        logger.info("MT5 is PAUSED - Skipping trade")
        db.log_trade(
            "MT5",
            data,
            "paused",
            0,
            details="Broker paused by user",
            webhook_received_at=webhook_received_at,
            raw_webhook=raw_webhook,
            rejected_reason="Broker paused"
        )
        return jsonify({"status": "paused", "message": "MT5 broker is paused"})

    try:
        # Get equity before trade
        equity_before = 0.0
        try:
            account_info = mt5.account_info()
            if account_info:
                equity_before = account_info.equity
        except:
            pass

        start_time = time.time()
        res = execute_trade(data)
        duration = (time.time() - start_time) * 1000

        STATE["last_trade"] = f"{data.get('action')} {data.get('symbol')}"

        status = 'success' if 'order' in res or res.get('status') == 'success' else 'error-mt5'

        # Get equity after trade
        equity_after = 0.0
        try:
            account_info = mt5.account_info()
            if account_info:
                equity_after = account_info.equity
        except:
            pass

        # Get current positions after trade
        position_after = ""
        try:
            positions = mt5.positions_get()
            if positions:
                position_after = json.dumps([{
                    "symbol": p.symbol,
                    "type": "BUY" if p.type == 0 else "SELL",
                    "volume": p.volume,
                    "profit": p.profit
                } for p in positions])
        except:
            pass

        # Database Log (Enhanced with full trade verification data)
        db.log_trade(
            "MT5",
            data,
            status,
            duration,
            details=str(res),
            expected_price=res.get('expected_price', 0.0),
            executed_price=res.get('executed_price', 0.0),
            slippage=res.get('slippage', 0.0),
            order_id=str(res.get('order', '')),
            ticket=str(res.get('order', '')),
            webhook_received_at=webhook_received_at,
            raw_webhook=raw_webhook,
            fill_time_ms=duration,
            broker_response=json.dumps(res) if isinstance(res, dict) else str(res),
            position_after=position_after,
            equity_before=equity_before,
            equity_after=equity_after
        )

        # Alert (Only on success to avoid spamming errors if simple check fail)
        if status == 'success':
            alerts.send_trade_alert(data, platform="MT5")

        return jsonify(res)
    except Exception as e:
        logger.error(f"Error: {e}")
        alerts.send_error_alert(str(e), context="MT5_Bridge_Main")
        db.log_trade(
            "MT5",
            data,
            "error",
            0,
            details=str(e),
            webhook_received_at=webhook_received_at,
            raw_webhook=raw_webhook,
            rejected_reason=str(e)
        )
        return jsonify({"error": str(e)}), 500

def handle_topstep_logic(data):
    """
    TopStep Trade Logic:
    - Converts Mini contracts to Micro contracts
    - 1 Mini = 5 Micros (configurable via micros_per_mini)
    - Max 15 Micros (configurable via max_micros)
    - Always trades MNQ (Micro NQ) regardless of input symbol
    """
    try:
        if not CONFIG.get('topstep', {}).get('enabled', False):
            return

        action = data.get('action', '').upper()
        raw_symbol = data.get('symbol', '').upper()

        # Get conversion settings from config
        micros_per_mini = CONFIG.get('topstep', {}).get('micros_per_mini', 5)
        max_micros = CONFIG.get('topstep', {}).get('max_micros', 15)

        # Always use MNQ for TopStep (Micro NQ)
        ts_symbol = "MNQ"

        # Calculate volume: 1 Mini = X Micros, capped at max
        if action not in ['CLOSE', 'EXIT', 'FLATTEN']:
            input_minis = float(data.get('volume', 1))
            raw_micros = input_minis * micros_per_mini
            ts_volume = min(raw_micros, max_micros)  # Cap at max

            logger.info(f"TopStep Conversion: {input_minis} Mini(s) = {raw_micros} Micros -> {ts_volume} MNQ (capped at {max_micros})")
        else:
            ts_volume = 0

        # Prepare payload
        ts_payload = {
            "symbol": ts_symbol,
            "action": action,
            "volume": ts_volume
        }

        # Pass through price for LIMIT orders
        if data.get('price'):
            ts_payload['price'] = float(data.get('price'))
        if data.get('sl'):
            ts_payload['sl'] = float(data.get('sl'))
        if data.get('tp'):
            ts_payload['tp'] = float(data.get('tp'))

        # Execute trade
        ts_res = ts_client.execute_trade(ts_payload)

        # Log result
        log_level = logging.INFO if ts_res.get('status') == 'success' else logging.ERROR
        logger.log(log_level, f"TopStep Response: {ts_res}")

        # DB Log
        status = ts_res.get('status', 'unknown')
        db.log_trade("TopStep", ts_payload, status, details=str(ts_res))

    except Exception as e:
        logger.error(f"TopStep Logic Error: {e}")

def hard_exit_callback(platform):
    """Callback for the scheduler to close all positions."""
    logger.warning(f"HARD EXIT: Closing all positions on {platform}")
    try:
        if platform.upper() == 'MT5':
            # Close all MT5 positions
            all_positions = mt5.positions_get()
            if all_positions:
                for pos in all_positions:
                    close_positions(pos.symbol)
                logger.info(f"Hard Exit: Closed {len(all_positions)} MT5 positions")
            else:
                logger.info("Hard Exit: No MT5 positions to close")

        elif platform.upper() == 'TOPSTEP':
            ts_client.execute_trade({"action": "CLOSE", "symbol": "MNQ"})

        elif platform.upper() == 'IBKR':
            forward_to_ibkr({"action": "CLOSE", "symbol": ""})

    except Exception as e:
        logger.error(f"Hard Exit callback error for {platform}: {e}")

# Initialize Trading Scheduler
scheduler = TradingScheduler(CONFIG, hard_exit_callback)

if __name__ == "__main__":
    # Check auto_connect setting (default True for backwards compatibility)
    auto_connect = MT5_CONF.get('auto_connect', True)

    if auto_connect:
        if not initialize_mt5():
            logger.warning("MT5 Init Failed - Running in Offline Mode")
    else:
        logger.info("MT5 Auto-connect disabled. Waiting for manual connection.")
        STATE["connected"] = False

    # Start the trading scheduler for hard exit
    scheduler.start()
    logger.info(f"Trading Scheduler active - Hard exit at {CONFIG.get('trading_hours', {}).get('hard_exit_time', '16:50')} ET")

    port = CONFIG['server']['mt5_port']
    logger.info(f"Starting MT5 Bridge on {port} (Waitress Production Server)")
    serve(app, host="0.0.0.0", port=port, threads=12)
