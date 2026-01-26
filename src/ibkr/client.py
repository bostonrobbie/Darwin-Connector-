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

    async def resolve_contract(self, symbol, sec_type, currency, exchange):
        """Resolves contract, supporting Futures Front Month."""
        if sec_type == 'FUT':
            contract = Future(symbol, exchange, currency)
            try:
                details = await self.ib.reqContractDetailsAsync(contract)
                if not details: raise Exception("No contracts found")
                
                today = datetime.now().strftime('%Y%m%d')
                valid = [d.contract for d in details if d.contract.lastTradeDateOrContractMonth and d.contract.lastTradeDateOrContractMonth >= today]
                
                if not valid: raise Exception("No valid future contracts")
                
                valid.sort(key=lambda c: c.lastTradeDateOrContractMonth)
                return valid[0]
            except Exception as e:
                logger.error(f"Future resolution failed: {e}")
                # Fallback?
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
        symbol = data.get('symbol', 'EURUSD').upper()
        
        # CLOSE / FLATTEN Logic
        if action in ['CLOSE', 'EXIT', 'FLATTEN']:
            return await self.close_position(symbol)

        qty = float(data.get('volume', 1))
        order_type = data.get('type', 'MARKET').upper()
        price = float(data.get('price', 0.0))
        
        # Contract
        contract = await self.resolve_contract(
            symbol, 
            data.get('secType', 'CASH'), 
            data.get('currency', 'USD'), 
            data.get('exchange', 'SMART')
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
