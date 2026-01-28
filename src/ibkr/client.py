from ib_async import *
import asyncio
import logging
import json
import os
import random
from datetime import datetime

logger = logging.getLogger("IBKR_Client")

class IBKRClient:
    def __init__(self, config):
        self.config = config
        self.ib = IB()
        self.client_id = config['ibkr']['client_id']
        self.host = config['ibkr']['tws_host']
        self.port = config['ibkr']['tws_port']
        self.api_key = config['ibkr'].get('api_key', '')

        # Position sizing config
        self.sizing = config['ibkr'].get('position_sizing', {})
        self.micros_per_mini = self.sizing.get('micros_per_mini', 1)
        self.max_micros = self.sizing.get('max_micros', 3)
        self.sizing_mode = self.sizing.get('mode', 'fixed')
        self.equity_config = self.sizing.get('equity_mode', {})

        # Symbol mapping (NQ -> MNQ, etc.)
        self.symbol_map = config['ibkr'].get('symbol_map', {})
        self.default_exchange = config['ibkr'].get('default_exchange', 'CME')
        self.default_currency = config['ibkr'].get('default_currency', 'USD')
        
    async def connect(self):
        """Connects to TWS/Gateway."""
        if self.ib.isConnected():
            return True
            
        try:
            # Randomize Client ID to avoid "Client ID already in use" errors on restart
            cid = random.randint(1000, 9999) 
            logger.info(f"Connecting to IBKR {self.host}:{self.port} (ID: {cid})...")
            
            await self.ib.connectAsync(self.host, self.port, clientId=cid)
            logger.info("✅ Connected to Interactive Brokers")
            return True
        except Exception as e:
            logger.error(f"Connection Failed: {e}")
            return False

    def is_connected(self):
        return self.ib.isConnected()

    def map_symbol(self, symbol):
        """Maps incoming symbol to IBKR symbol (e.g., NQ -> MNQ)."""
        mapped = self.symbol_map.get(symbol.upper(), symbol.upper())
        if mapped != symbol.upper():
            logger.info(f"Symbol mapped: {symbol} -> {mapped}")
        return mapped

    def calculate_quantity(self, requested_qty, symbol=None):
        """
        Calculate actual quantity based on position sizing config.
        - fixed mode: micros_per_mini conversion, capped at max_micros
        - equity mode: calculate based on account equity percentage
        """
        if self.sizing_mode == 'equity' and self.equity_config.get('enabled', False):
            return self._calculate_equity_based_qty(requested_qty, symbol)

        # Fixed mode: 1 mini = micros_per_mini micros
        qty = int(requested_qty * self.micros_per_mini)
        qty = min(qty, self.max_micros)  # Cap at max
        logger.info(f"Position sizing: {requested_qty} -> {qty} contracts (mode={self.sizing_mode}, max={self.max_micros})")
        return max(1, qty)

    def _calculate_equity_based_qty(self, requested_qty, symbol=None):
        """Calculate quantity based on account equity percentage."""
        try:
            base_equity = self.equity_config.get('base_equity', 10000)
            risk_pct = self.equity_config.get('risk_per_trade_pct', 1.0)
            max_pos_pct = self.equity_config.get('max_position_pct', 5.0)
            scale_factor = self.equity_config.get('scale_factor', 1.0)

            # Get current account equity (if connected)
            account_equity = base_equity
            if self.ib.isConnected():
                account_values = self.ib.accountSummary()
                for av in account_values:
                    if av.tag == 'NetLiquidation':
                        account_equity = float(av.value)
                        break

            # Calculate position size based on equity
            risk_amount = account_equity * (risk_pct / 100.0)
            max_amount = account_equity * (max_pos_pct / 100.0)

            # For futures, assume ~$500 margin per micro
            margin_per_contract = 500
            qty_from_risk = int(risk_amount / margin_per_contract * scale_factor)
            qty_from_max = int(max_amount / margin_per_contract)

            qty = min(qty_from_risk, qty_from_max, self.max_micros)
            logger.info(f"Equity sizing: equity=${account_equity:.0f}, risk={risk_pct}%, qty={qty}")
            return max(1, qty)

        except Exception as e:
            logger.error(f"Equity calculation failed: {e}, using fixed sizing")
            return min(int(requested_qty * self.micros_per_mini), self.max_micros)

    async def get_account_equity(self):
        """Get current account net liquidation value."""
        if not self.ib.isConnected():
            return None
        try:
            account_values = self.ib.accountSummary()
            for av in account_values:
                if av.tag == 'NetLiquidation':
                    return float(av.value)
        except Exception as e:
            logger.error(f"Failed to get account equity: {e}")
        return None

    async def resolve_contract(self, symbol, sec_type, currency, exchange):
        """Resolves contract, supporting Futures Front Month."""
        if sec_type == 'FUT':
            # For MNQ/MES, exchange should be CME/GLOBEX
            fut_exchange = 'CME' if exchange in ['CME', 'GLOBEX', 'SMART'] else exchange
            # Create contract with proper parameters
            contract = Future(symbol=symbol, exchange=fut_exchange, currency=currency)
            logger.info(f"Resolving futures contract: {symbol} on {fut_exchange}")
            try:
                details = await self.ib.reqContractDetailsAsync(contract)
                if not details:
                    raise Exception(f"No contracts found for {symbol}")

                today = datetime.now().strftime('%Y%m%d')
                valid = [d.contract for d in details if d.contract.lastTradeDateOrContractMonth and d.contract.lastTradeDateOrContractMonth >= today]

                if not valid:
                    raise Exception(f"No valid future contracts for {symbol}")

                valid.sort(key=lambda c: c.lastTradeDateOrContractMonth)
                front_month = valid[0]
                logger.info(f"Resolved {symbol} to front month: {front_month.localSymbol} (expires {front_month.lastTradeDateOrContractMonth})")
                return front_month
            except Exception as e:
                logger.error(f"Future resolution failed for {symbol}: {e}")
                return contract
        
        # Standard Types
        if sec_type == 'CASH':
            return Forex(symbol[:3], symbol[3:]) if len(symbol)==6 else Forex(symbol)
        elif sec_type == 'STK':
            return Stock(symbol, exchange, currency)
        elif sec_type == 'CRYPTO':
            return Crypto(symbol, exchange, currency)
        
        return Contract(symbol=symbol, secType=sec_type, exchange=exchange, currency=currency)

    async def execute_trade(self, data):
        """Executes a trade based on webhook data."""
        if not self.ib.isConnected():
            if not await self.connect():
                return {"status": "error", "message": "IBKR Disconnected"}

        action = data.get('action', 'BUY').upper()
        raw_symbol = data.get('symbol', 'EURUSD').upper()

        # Map symbol (NQ -> MNQ, etc.)
        symbol = self.map_symbol(raw_symbol)

        # CLOSE / FLATTEN Logic
        if action in ['CLOSE', 'EXIT', 'FLATTEN']:
            return await self.close_position(symbol)

        raw_qty = float(data.get('volume', 1))
        order_type = data.get('type', 'MARKET').upper()
        price = float(data.get('price', 0.0))

        # Apply position sizing (1 mini = 1 micro, max 3)
        sec_type = data.get('secType', 'CASH')
        if sec_type == 'FUT':
            qty = self.calculate_quantity(raw_qty, symbol)
        else:
            qty = raw_qty

        # Use defaults from config if not specified
        exchange = data.get('exchange', self.default_exchange if sec_type == 'FUT' else 'SMART')
        currency = data.get('currency', self.default_currency)

        # Contract
        contract = await self.resolve_contract(
            symbol,
            sec_type,
            currency,
            exchange
        )

        orders = []
        # Parent Order
        if order_type == 'LIMIT' and price > 0:
            parent = LimitOrder(action, qty, price)
        else:
            parent = MarketOrder(action, qty)
            
        # Bracket Logic (SL/TP)
        sl = float(data.get('sl', 0.0))
        tp = float(data.get('tp', 0.0))
        
        if sl > 0 or tp > 0:
            parent.transmit = False
            orders.append(parent)
            
            reverse = 'SELL' if action == 'BUY' else 'BUY'
            if sl > 0:
                orders.append(StopOrder(reverse, qty, sl, parentId=parent.orderId, transmit=(tp==0)))
            if tp > 0:
                orders.append(LimitOrder(reverse, qty, tp, parentId=parent.orderId, transmit=True))
        else:
            orders.append(parent)

        logger.info(f"Placing {len(orders)} orders for {symbol}...")
        
        trade = None
        for o in orders:
            trade = self.ib.placeOrder(contract, o)
            
        await asyncio.sleep(0.5)
        return {"status": "success", "order_id": trade.order.orderId if trade else 0}

    async def close_position(self, symbol):
        """Closes positions for a symbol."""
        await self.ib.reqPositionsAsync()
        count = 0
        for pos in self.ib.positions():
            # Check symbol match (simple string match)
            if symbol in pos.contract.symbol or symbol in pos.contract.localSymbol:
                if pos.position == 0: continue
                action = 'SELL' if pos.position > 0 else 'BUY'
                qty = abs(pos.position)
                logger.info(f"Closing {pos.contract.localSymbol}: {action} {qty}")
                self.ib.placeOrder(pos.contract, MarketOrder(action, qty))
                count += 1
        
        return {"status": "success", "closed_count": count}
