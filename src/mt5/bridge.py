import MetaTrader5 as mt5
import json
import os
import sys
import logging
import datetime
import time
import atexit
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import concurrent.futures
from waitress import serve
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
        config = json.load(f)

    # Override with environment variables if set (security: keep secrets out of config.json)
    if os.environ.get('MT5_LOGIN'):
        config['mt5']['login'] = int(os.environ.get('MT5_LOGIN'))
    if os.environ.get('MT5_PASSWORD'):
        config['mt5']['password'] = os.environ.get('MT5_PASSWORD')
    if os.environ.get('MT5_SERVER'):
        config['mt5']['server'] = os.environ.get('MT5_SERVER')
    if os.environ.get('TOPSTEP_USERNAME'):
        config['topstep']['username'] = os.environ.get('TOPSTEP_USERNAME')
    if os.environ.get('TOPSTEP_API_KEY'):
        config['topstep']['api_key'] = os.environ.get('TOPSTEP_API_KEY')
    if os.environ.get('TOPSTEP_ACCOUNT_ID'):
        config['topstep']['account_id'] = int(os.environ.get('TOPSTEP_ACCOUNT_ID'))
    if os.environ.get('WEBHOOK_SECRET'):
        config['security']['webhook_secret'] = os.environ.get('WEBHOOK_SECRET')
    if os.environ.get('DISCORD_WEBHOOK_URL'):
        config['alerts']['discord_webhook'] = os.environ.get('DISCORD_WEBHOOK_URL')

    return config

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

# Ensure executor is cleaned up on exit
def _shutdown_executor():
    executor.shutdown(wait=False)
atexit.register(_shutdown_executor)

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
    """Wraps order_send with retry logic for transient errors.

    Optimized delays for low-latency execution:
    - 0.1s, 0.3s, 0.5s for transient errors (reduced from 0.5s, 1.0s, 1.0s)
    """
    delays = [0.1, 0.3, 0.5]  # Progressive backoff, optimized for speed

    for i in range(max_retries):
        try:
            res = mt5.order_send(request)
            if res is None:
                logger.error(f"Order Send returned None (Attempt {i+1})")
                time.sleep(delays[i] if i < len(delays) else 0.5)
                continue

            if res.retcode == mt5.TRADE_RETCODE_DONE:
                return res
            elif res.retcode in [mt5.TRADE_RETCODE_TIMEOUT, mt5.TRADE_RETCODE_CONNECTION]:
                logger.warning(f"Transient Error {res.retcode}: {res.comment}. Retrying in {delays[i]}s...")
                time.sleep(delays[i] if i < len(delays) else 0.5)
            else:
                # Fatal error (e.g. Invalid Volume)
                logger.error(f"Fatal Order Error {res.retcode}: {res.comment}")
                return res
        except Exception as e:
            logger.error(f"Exception during order send: {e}")
            time.sleep(delays[i] if i < len(delays) else 0.5)

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

    # Log tick data for slippage analysis
    tick_spread = tick.ask - tick.bid
    logger.info(f"TICK DATA: bid={tick.bid}, ask={tick.ask}, spread={tick_spread:.4f}")

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

    # Log tick data for slippage analysis
    if tick:
        spread = tick.ask - tick.bid if tick.ask and tick.bid else 0
        logger.info(f"TICK DATA: bid={tick.bid:.5f}, ask={tick.ask:.5f}, spread={spread:.5f}")

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

    # Log full order request for debugging
    logger.info(f"ORDER REQUEST: {json.dumps(req, default=str)}")

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
        "slippage": slippage,
        "bid_price": tick.bid,
        "ask_price": tick.ask,
        "spread": tick.ask - tick.bid
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

def forward_to_ibkr_blocking(data):
    """Forwards to IBKR and WAITS for response (not fire-and-forget)."""
    start_time = time.time()
    try:
        ibkr_port = CONFIG['server'].get('ibkr_port', 5001)
        url = f"http://127.0.0.1:{ibkr_port}/webhook"

        payload = data.copy()
        payload['secret'] = CONFIG['security']['webhook_secret']

        # Symbol cleanup for IBKR
        raw = payload.get('symbol', '').upper()
        if '1!' in raw:
            payload['symbol'] = raw.replace('1!', '').replace('2!', '')
            payload['secType'] = 'FUT'
            payload['exchange'] = 'GLOBEX'

        response = requests.post(url, json=payload, timeout=10.0)
        duration = (time.time() - start_time) * 1000

        result = response.json() if response.status_code == 200 else {'error': response.text}
        result['duration_ms'] = duration
        result['status'] = 'success' if response.status_code == 200 else 'error'

        logger.info(f"IBKR Response: {result}")
        return result

    except requests.exceptions.Timeout:
        duration = (time.time() - start_time) * 1000
        logger.error(f"IBKR Timeout after {duration:.0f}ms")
        return {'status': 'timeout', 'error': 'IBKR bridge timeout', 'duration_ms': duration}
    except Exception as e:
        duration = (time.time() - start_time) * 1000
        logger.error(f"IBKR Error: {e}")
        return {'status': 'error', 'error': str(e), 'duration_ms': duration}

def handle_topstep_logic_blocking(data):
    """Wrapper for TopStep that returns a result dict."""
    start_time = time.time()
    try:
        # Call the existing TopStep logic
        handle_topstep_logic(data)
        duration = (time.time() - start_time) * 1000
        return {'status': 'success', 'duration_ms': duration}
    except Exception as e:
        duration = (time.time() - start_time) * 1000
        logger.error(f"TopStep Error: {e}")
        return {'status': 'error', 'error': str(e), 'duration_ms': duration}

def capture_pre_trade_state():
    """Capture position state before trade for comprehensive logging."""
    state = {'positions': [], 'equity': 0.0, 'margin': 0.0, 'free_margin': 0.0}
    try:
        account = mt5.account_info()
        if account:
            state['equity'] = account.equity
            state['margin'] = account.margin
            state['free_margin'] = account.margin_free

        positions = mt5.positions_get()
        if positions:
            state['positions'] = [{
                'symbol': p.symbol,
                'volume': p.volume,
                'type': 'BUY' if p.type == 0 else 'SELL',
                'profit': p.profit,
                'ticket': p.ticket
            } for p in positions]
    except Exception as e:
        logger.error(f"Pre-trade state capture error: {e}")
    return state

def execute_mt5_blocking(data, webhook_received_at, raw_webhook):
    """Execute MT5 trade and return result dict."""
    start_time = time.time()
    try:
        # Capture pre-trade state
        pre_trade_state = capture_pre_trade_state()
        logger.info(f"PRE-TRADE STATE: equity={pre_trade_state['equity']:.2f}, positions={len(pre_trade_state['positions'])}")
        if pre_trade_state['positions']:
            logger.info(f"  Existing positions: {json.dumps(pre_trade_state['positions'], default=str)}")

        # Get equity before trade
        equity_before = pre_trade_state['equity']

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

        # Database Log with comprehensive tick data
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
            equity_after=equity_after,
            pre_trade_positions=json.dumps(pre_trade_state['positions']) if pre_trade_state['positions'] else None,
            bid_price=res.get('bid_price', 0.0),
            ask_price=res.get('ask_price', 0.0),
            spread=res.get('spread', 0.0)
        )

        # Alert on success
        if status == 'success':
            alerts.send_trade_alert(data, platform="MT5")

        res['status'] = status
        res['duration_ms'] = duration
        return res

    except Exception as e:
        duration = (time.time() - start_time) * 1000
        logger.error(f"MT5 Error: {e}")
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
        return {'status': 'error', 'error': str(e), 'duration_ms': duration}

def execute_all_brokers_parallel(data, config, webhook_received_at, raw_webhook):
    """Execute trades on all 3 brokers in TRUE parallel."""
    results = {'mt5': None, 'ibkr': None, 'topstep': None}
    futures = {}

    # Submit all broker executions to thread pool SIMULTANEOUSLY
    if not is_broker_paused(config, 'mt5'):
        futures['mt5'] = executor.submit(execute_mt5_blocking, data, webhook_received_at, raw_webhook)
    else:
        results['mt5'] = {'status': 'paused', 'reason': 'Broker paused by user'}
        logger.info("MT5 is PAUSED - Skipping trade")

    if not is_broker_paused(config, 'ibkr'):
        futures['ibkr'] = executor.submit(forward_to_ibkr_blocking, data)
    else:
        results['ibkr'] = {'status': 'paused', 'reason': 'Broker paused by user'}
        logger.info("IBKR is PAUSED - Skipping trade forwarding")

    if not is_broker_paused(config, 'topstep'):
        futures['topstep'] = executor.submit(handle_topstep_logic_blocking, data)
    else:
        results['topstep'] = {'status': 'paused', 'reason': 'Broker paused by user'}
        logger.info("TopStep is PAUSED - Skipping trade")

    # Wait for all with timeout (10s per broker)
    for broker, future in futures.items():
        try:
            results[broker] = future.result(timeout=10.0)
        except concurrent.futures.TimeoutError:
            results[broker] = {'status': 'timeout', 'error': f'{broker} execution timed out'}
            logger.error(f"{broker} execution timed out")
        except Exception as e:
            results[broker] = {'status': 'error', 'error': str(e)}
            logger.error(f"{broker} execution error: {e}")

    return results

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

@app.route('/ping', methods=['GET', 'POST'])
def ping():
    """Simple ping endpoint to verify server is reachable."""
    return jsonify({
        "status": "ok",
        "message": "Webhook server is running",
        "timestamp": datetime.datetime.now().isoformat(),
        "server": "MT5_Bridge"
    })

# Store verification tokens for round-trip testing
_verification_tokens = {}

@app.route('/webhook/verify', methods=['POST'])
def webhook_verify():
    """
    Verification endpoint for round-trip webhook testing.
    Receives a verification token and stores it to confirm the webhook URL is reachable.
    """
    data = request.json or {}
    token = data.get('verification_token')

    if not token:
        return jsonify({"error": "Missing verification_token"}), 400

    # Store the token with timestamp
    _verification_tokens[token] = {
        "received_at": datetime.datetime.now().isoformat(),
        "remote_addr": request.remote_addr
    }

    logger.info(f"Webhook verification received: token={token[:8]}... from {request.remote_addr}")

    return jsonify({
        "status": "verified",
        "token": token,
        "received_at": _verification_tokens[token]["received_at"],
        "server": "MT5_Bridge"
    })

@app.route('/webhook/verify/<token>', methods=['GET'])
def check_verification(token):
    """
    Check if a verification token was received.
    Used by the verification function to confirm round-trip success.
    """
    if token in _verification_tokens:
        result = _verification_tokens.pop(token)  # Remove after checking
        return jsonify({
            "status": "success",
            "verified": True,
            "received_at": result["received_at"],
            "remote_addr": result["remote_addr"]
        })
    else:
        return jsonify({
            "status": "pending",
            "verified": False,
            "message": "Token not yet received"
        })

@app.route('/webhook/test', methods=['GET', 'POST'])
def webhook_test():
    """
    Debug endpoint to test webhook receipt.
    Accepts ANY request and logs all details for troubleshooting.
    Use this to verify TradingView can reach your server.
    """
    received_at = datetime.datetime.now().isoformat()

    # Capture everything about the request
    debug_info = {
        "status": "received",
        "received_at": received_at,
        "method": request.method,
        "path": request.path,
        "remote_addr": request.remote_addr,
        "headers": dict(request.headers),
        "args": dict(request.args),
        "content_type": request.content_type,
    }

    # Try to get body data
    try:
        if request.is_json:
            debug_info["json_body"] = request.json
        else:
            debug_info["raw_body"] = request.get_data(as_text=True)
    except Exception as e:
        debug_info["body_error"] = str(e)

    # Log it
    logger.info(f"WEBHOOK TEST RECEIVED: {json.dumps(debug_info, indent=2, default=str)}")

    # Check if it looks like a valid TradingView webhook
    validation = {
        "has_secret": False,
        "secret_valid": False,
        "has_action": False,
        "has_symbol": False,
        "ready_for_live": False
    }

    if request.is_json and request.json:
        data = request.json
        validation["has_secret"] = "secret" in data
        validation["secret_valid"] = data.get("secret") == CONFIG['security']['webhook_secret']
        validation["has_action"] = "action" in data
        validation["has_symbol"] = "symbol" in data
        validation["ready_for_live"] = all([
            validation["secret_valid"],
            validation["has_action"],
            validation["has_symbol"]
        ])

    debug_info["validation"] = validation

    if validation["ready_for_live"]:
        debug_info["message"] = "SUCCESS! Your webhook is correctly formatted. Change /webhook/test to /webhook for live trading."
    elif validation["has_secret"] and not validation["secret_valid"]:
        debug_info["message"] = "ERROR: Secret does not match. Check your webhook_secret in config.json"
    else:
        debug_info["message"] = "Webhook received but missing required fields. Need: secret, action, symbol"

    return jsonify(debug_info)

@app.route('/webhook/info', methods=['GET'])
def webhook_info():
    """Returns the expected webhook format and current configuration."""
    mt5_subdomain = CONFIG.get('tunnels', {}).get('mt5_subdomain', 'major-cups-pick')

    return jsonify({
        "webhook_url": f"https://{mt5_subdomain}.loca.lt/webhook",
        "test_url": f"https://{mt5_subdomain}.loca.lt/webhook/test",
        "health_url": f"https://{mt5_subdomain}.loca.lt/health",
        "expected_format": {
            "secret": CONFIG['security']['webhook_secret'],
            "action": "BUY | SELL | CLOSE | EXIT | FLATTEN",
            "symbol": "NQ1! | MNQ1! | ES1! | MES1!",
            "volume": 1.0,
            "time": "{{timenow}}"
        },
        "tradingview_alert_template": {
            "secret": CONFIG['security']['webhook_secret'],
            "action": "{{strategy.order.action}}",
            "symbol": "{{ticker}}",
            "volume": "{{strategy.order.contracts}}",
            "time": "{{timenow}}"
        },
        "manual_buy_example": {
            "secret": CONFIG['security']['webhook_secret'],
            "action": "BUY",
            "symbol": "NQ1!",
            "volume": 1
        },
        "manual_sell_example": {
            "secret": CONFIG['security']['webhook_secret'],
            "action": "SELL",
            "symbol": "NQ1!",
            "volume": 1
        },
        "close_example": {
            "secret": CONFIG['security']['webhook_secret'],
            "action": "CLOSE",
            "symbol": "NQ1!",
            "volume": 1
        }
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

    # === TRUE PARALLEL EXECUTION ===
    # All 3 brokers execute simultaneously in thread pool
    start_time = time.time()
    results = execute_all_brokers_parallel(data, current_config, webhook_received_at, raw_webhook)
    total_duration = (time.time() - start_time) * 1000

    # Log execution summary
    success_count = sum(1 for r in results.values() if r and r.get('status') == 'success')
    logger.info(f"Parallel Execution Complete: {success_count}/3 succeeded in {total_duration:.0f}ms")
    logger.info(f"Results: MT5={results.get('mt5', {}).get('status')}, IBKR={results.get('ibkr', {}).get('status')}, TopStep={results.get('topstep', {}).get('status')}")

    # Return aggregated response
    return jsonify({
        "status": "completed",
        "total_duration_ms": round(total_duration, 2),
        "results": results
    })

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
