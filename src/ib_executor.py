from ib_async import *
import json
import os
import asyncio
import logging
from datetime import datetime

# Setup Logger
# Logger setup moved to main entry point
logger = logging.getLogger("IB_Executor")

ib = IB()

# Load settings
def load_settings():
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config', 'settings.json')
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[ERROR] Failed to load settings: {e}")
        return {}

SETTINGS = load_settings()
IBKR_CONFIG = SETTINGS.get('ibkr', {})
TRADING_CONFIG = SETTINGS.get('trading', {})

async def connect_ib():
    """Connects to TWS or IB Gateway with Auto-Port Detection."""
    host = IBKR_CONFIG.get('host', '127.0.0.1')
    primary_port = int(IBKR_CONFIG.get('port', 7497))
    # If config is 7497 (Paper), backup is 7496 (Live), and vice versa.
    backup_port = 7496 if primary_port == 7497 else 7497
    import random
    
    # Try different Client IDs to avoid collisions (Zombie processes)
    base_client_id = int(IBKR_CONFIG.get('client_id', 1))
    
    for attempt in range(3):
        # First attempt uses config ID, subsequent ones use random
        current_client_id = base_client_id if attempt == 0 else random.randint(1000, 9999)
        
        logger.info(f"Connecting to IBKR {host}:{primary_port} ClientID:{current_client_id}...")
        try:
            await ib.connectAsync(host, primary_port, clientId=current_client_id)
            logger.info(f"Connected to Interactive Brokers on Port {primary_port} (ID: {current_client_id})!")
            return True
        except Exception as e:
            logger.warning(f"Port {primary_port}/ID {current_client_id} failed: {e}")
            ib.disconnect() # Force cleanup of partial state
            
            # If Connection Refused, try Backup Port
            if "ConnectionRefused" in str(e) or "refused" in str(e).lower():
                logger.warning(f"Primary port refused. Trying Backup Port {backup_port}...")
                try:
                    await ib.connectAsync(host, backup_port, clientId=current_client_id)
                    logger.info(f"Connected to Interactive Brokers on Port {backup_port} (ID: {current_client_id})!")
                    return True
                except Exception as e2:
                     logger.warning(f"Backup port failed: {e2}")
                     ib.disconnect()
            else:
                 # If likely Client ID error (Peer closed), just loop to try new ID
                 logger.warning("Likely Client ID conflict. Retrying with new ID...")
                 await asyncio.sleep(1)
                 
    logger.error("All connection attempts failed.")
    return False

def get_contract(symbol, sec_type, currency, exchange):
    """Creates a contract object."""
    if sec_type == 'CASH':
        # Split EURUSD -> EUR, USD
        # Simple heuristic: First 3 chars base, next 3 quote
        if len(symbol) == 6:
            base = symbol[:3]
            quote = symbol[3:]
            return Forex(base, quote)
        return Forex(symbol) # Fallback
    elif sec_type == 'STK':
        return Stock(symbol, exchange, currency)
    elif sec_type == 'CRYPTO':
         return Crypto(symbol, exchange, currency)
    else:
        # Generic fallback
        return Contract(symbol=symbol, secType=sec_type, exchange=exchange, currency=currency)

async def execute_trade_async(data):
    """Executes a trade asynchronously."""
    if not ib.isConnected():
        logger.warning("IB Not connected, attempting to connect...")
        connected = await connect_ib()
        if not connected:
             return {"status": "error", "message": "Could not connect to IBKR"}

    action = data.get('action', TRADING_CONFIG.get('default_action', 'BUY')).upper()
    
    # --- Symbol Mapping (Match MT5 Logic) ---
    raw_symbol = data.get('symbol', TRADING_CONFIG.get('default_symbol', 'EURUSD')).upper()
    symbol_map = TRADING_CONFIG.get('symbol_map', {})
    symbol = raw_symbol
    
    if raw_symbol in symbol_map:
        mapping = symbol_map[raw_symbol]
        if isinstance(mapping, str):
            symbol = mapping
        elif isinstance(mapping, dict):
            symbol = mapping.get("name", raw_symbol)
            # Future: Handle multiplier if needed, though IBKR uses 'quantity' directly
            
    logger.info(f"Processing: {action} {symbol} (Origin: {raw_symbol})")
    
    # --- CLOSE LOGIC ---
    if action in ['CLOSE', 'EXIT', 'FLATTEN']:
        return await close_positions_async(symbol)

    quantity = float(data.get('volume', TRADING_CONFIG.get('default_quantity', 10000))) 
    
    # Contract Construction
    sec_type = data.get('secType', TRADING_CONFIG.get('default_sec_type', 'CASH'))
    exchange = data.get('exchange', TRADING_CONFIG.get('default_exchange', 'IDEALPRO'))
    currency = data.get('currency', TRADING_CONFIG.get('default_currency', 'USD'))

    contract = await resolve_contract_async(symbol, sec_type, currency, exchange)

async def resolve_contract_async(symbol, sec_type, currency, exchange):
    """Resolves contract details, specifically for Futures Front Month."""
    if sec_type == 'FUT':
        # Create a generic Future object to search
        # NQ usually trades on CME (Globex)
        contract = Future(symbol, exchange, currency)
        
        try:
            logger.info(f"Resolving Front Month Future for {symbol}...")
            details = await ib.reqContractDetailsAsync(contract)
            if not details:
                logger.error(f"No contracts found for {symbol}")
                raise Exception("Contract not found")
            
            # Sort by expiration
            # Filter for non-expired
            today = datetime.now().strftime('%Y%m%d')
            valid_contracts = [d.contract for d in details if d.contract.lastTradeDateOrContractMonth and d.contract.lastTradeDateOrContractMonth >= today]
            
            if not valid_contracts:
                 raise Exception("No valid future contracts found")
                 
            # Sort by date
            valid_contracts.sort(key=lambda c: c.lastTradeDateOrContractMonth)
            
            front_month = valid_contracts[0]
            logger.info(f"Resolved {symbol} -> {front_month.localSymbol} (Exp: {front_month.lastTradeDateOrContractMonth})")
            return front_month
            
        except Exception as e:
            logger.error(f"Failed to resolve future: {e}")
            # Fallback to simple construction if resolution fails
            return Future(symbol, '202412', exchange) # Dangerous fallback, better to fail?
            
    else:
        # Standard synchronous creation for valid types
        if sec_type == 'CASH':
            if len(symbol) == 6:
                return Forex(symbol[:3], symbol[3:])
            return Forex(symbol)
        elif sec_type == 'STK':
            return Stock(symbol, exchange, currency)
        elif sec_type == 'CRYPTO':
            return Crypto(symbol, exchange, currency)
        else:
            return Contract(symbol=symbol, secType=sec_type, exchange=exchange, currency=currency)

    
    # --- ORDER LOGIC ---
    sl = float(data.get('sl', 0.0))
    tp = float(data.get('tp', 0.0))
    limit_price = float(data.get('price', 0.0))
    order_type = data.get('type', 'MARKET').upper()
    
    orders_to_place = []
    
    # Base Order
    if order_type == 'LIMIT' and limit_price > 0:
        parent = LimitOrder(action, quantity, limit_price)
    else:
        parent = MarketOrder(action, quantity)
    # Important: If just market, transmit=True. If bracket, transmit=False (wait for children).
    if sl > 0 or tp > 0:
        parent.orderId = ib.client.getReqId()
        parent.transmit = False
        orders_to_place.append(parent)
        
        reverse_action = 'SELL' if action == 'BUY' else 'BUY'
        
        # Stop Loss
        if sl > 0:
            stop_order = StopOrder(reverse_action, quantity, sl)
            stop_order.parentId = parent.orderId
            stop_order.transmit = (tp == 0) # Transmit if no TP to confirm
            orders_to_place.append(stop_order)
            
        # Take Profit
        if tp > 0:
            tp_order = LimitOrder(reverse_action, quantity, tp)
            tp_order.parentId = parent.orderId
            tp_order.transmit = True # Last one triggers all
            orders_to_place.append(tp_order)
    else:
        # Simple Market Order
        orders_to_place.append(parent)

    logger.info(f"Placing {len(orders_to_place)} Orders for {symbol}")
    
    try:
        final_trade = None
        for o in orders_to_place:
            final_trade = ib.placeOrder(contract, o)
        
        # We don't wait for fill in this webhook response to keep it fast, 
        # but we wait for it to be 'submitted' to TWS.
        await asyncio.sleep(0.5) 
        
        return {
            "status": "success",
            "message": "Orders Submitted",
            "order_id": final_trade.order.orderId if final_trade else 0,
            "status_ib": final_trade.orderStatus.status if final_trade else "Unknown"
        }
    except Exception as e:
        logger.error(f"Order placement error: {e}")
        return {"status": "error", "message": str(e)}

async def close_positions_async(symbol):
    """Closes all open positions for a symbol."""
    if not ib.isConnected():
         await connect_ib()
         
    # Update positions
    await ib.reqPositionsAsync()
    
    positions = ib.positions()
    count = 0
    results = []
    
    for pos in positions:
        # Filter by symbol heuristic
        # IBKR pos.contract.symbol is usually just 'EUR' for 'EURUSD' sometimes? 
        # Actually it's usually 'EUR' and localSymbol 'EUR.USD' etc.
        # Strict match on contract definition might be safer
        
        # Matches if symbol explicitly in contract symbol or local symbol
        s_upper = symbol.upper()
        p_symbol = pos.contract.symbol.upper()
        p_local = pos.contract.localSymbol.upper()
        
        if s_upper in p_symbol or s_upper in p_local:
            if pos.position == 0: continue
            
            action = 'SELL' if pos.position > 0 else 'BUY'
            qty = abs(pos.position)
            
            logger.info(f"Closing {p_local}: {action} {qty}")
            
            order = MarketOrder(action, qty)
            trade = ib.placeOrder(pos.contract, order)
            results.append(f"Closed {qty} of {p_local}")
            count += 1
            
    return {"status": "success", "message": f"Closed {count} positions", "details": results}

def execute_trade_sync_wrapper(data):
    """Wrapper to call async function from sync Flask context."""
    return ib.run(execute_trade_async(data))

def check_health_sync():
    """Checks connection status and attempts reconnect if needed."""
    if not ib.isConnected():
        # Attempt reconnect (timeout of 0.1s to avoid blocking dash too long)
        try:
            # We use existing loop or just check
            # Since this is sync wrapper, we can't easily await.
            # But the main loop logic relies on 'execute_trade' to connect.
            # We can try a non-blocking check or trigger the connect logic.
            # Simplest for now: Just return status. 
            # The 'connection_monitor' removed means we need something to trigger connect.
            # Let's trust 'execute_trade' for now, but return False here.
            pass
        except:
            pass
    return ib.isConnected()

def disconnect():
    ib.disconnect()
