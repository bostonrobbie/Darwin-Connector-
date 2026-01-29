import sqlite3
import logging
import os
from datetime import datetime

logger = logging.getLogger("Database")

class DatabaseManager:
    def __init__(self, db_path='trades.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Creates tables if they don't exist and handles migrations."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Create initial table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        platform TEXT,
                        symbol TEXT,
                        action TEXT,
                        volume REAL,
                        status TEXT,
                        latency_ms REAL,
                        details TEXT,
                        expected_price REAL,
                        executed_price REAL,
                        slippage REAL
                    )
                ''')

                # Migration: Check if columns exist, if not, add them (Safe check)
                existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(trades)")]
                new_cols = {
                    "expected_price": "REAL",
                    "executed_price": "REAL",
                    "slippage": "REAL",
                    "order_id": "TEXT",
                    "ticket": "TEXT",
                    "webhook_received_at": "TEXT",
                    "raw_webhook": "TEXT",
                    "fill_time_ms": "REAL",
                    "broker_response": "TEXT",
                    "position_after": "TEXT",
                    "equity_before": "REAL",
                    "equity_after": "REAL",
                    "commission": "REAL",
                    "pnl": "REAL",
                    "rejected_reason": "TEXT",
                    # New columns for enhanced logging
                    "pre_trade_positions": "TEXT",  # JSON of positions before trade
                    "bid_price": "REAL",            # Tick bid at trade time
                    "ask_price": "REAL",            # Tick ask at trade time
                    "spread": "REAL",               # Spread at trade time
                }
                for col, dtype in new_cols.items():
                    if col not in existing_cols:
                        try:
                            logger.info(f"Migrating DB: Adding {col}...")
                            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {dtype}")
                        except Exception as e:
                            logger.error(f"Migration failed for {col}: {e}")

                conn.commit()
        except Exception as e:
            logger.error(f"DB Init Failed: {e}")

    def log_trade(self, platform, data, status, latency_ms=0, details="", expected_price=0.0,
                  executed_price=0.0, slippage=0.0, order_id=None, ticket=None,
                  webhook_received_at=None, raw_webhook=None, fill_time_ms=0.0,
                  broker_response=None, position_after=None, equity_before=0.0,
                  equity_after=0.0, commission=0.0, pnl=0.0, rejected_reason=None,
                  pre_trade_positions=None, bid_price=0.0, ask_price=0.0, spread=0.0):
        """Logs a trade execution with comprehensive metrics for verification."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trades (
                        timestamp, platform, symbol, action, volume, status, latency_ms,
                        details, expected_price, executed_price, slippage, order_id, ticket,
                        webhook_received_at, raw_webhook, fill_time_ms, broker_response,
                        position_after, equity_before, equity_after, commission, pnl, rejected_reason,
                        pre_trade_positions, bid_price, ask_price, spread
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(),
                    platform,
                    data.get('symbol'),
                    data.get('action'),
                    float(data.get('volume', 0)),
                    status,
                    latency_ms,
                    str(details),
                    expected_price,
                    executed_price,
                    slippage,
                    order_id,
                    ticket,
                    webhook_received_at,
                    raw_webhook,
                    fill_time_ms,
                    broker_response,
                    position_after,
                    equity_before,
                    equity_after,
                    commission,
                    pnl,
                    rejected_reason,
                    pre_trade_positions,
                    bid_price,
                    ask_price,
                    spread
                ))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")
            return None

    def get_trades(self, limit=100, platform=None, start_date=None, end_date=None):
        """Retrieve trades with optional filters for verification."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                query = "SELECT * FROM trades WHERE 1=1"
                params = []

                if platform:
                    query += " AND platform = ?"
                    params.append(platform)
                if start_date:
                    query += " AND timestamp >= ?"
                    params.append(start_date)
                if end_date:
                    query += " AND timestamp <= ?"
                    params.append(end_date)

                query += " ORDER BY id DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []

    def get_trade_summary(self, start_date=None, end_date=None):
        """Get trade summary statistics for verification."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                query = """
                    SELECT
                        platform,
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
                        SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed,
                        AVG(latency_ms) as avg_latency_ms,
                        AVG(slippage) as avg_slippage,
                        SUM(pnl) as total_pnl,
                        SUM(commission) as total_commission
                    FROM trades
                    WHERE 1=1
                """
                params = []

                if start_date:
                    query += " AND timestamp >= ?"
                    params.append(start_date)
                if end_date:
                    query += " AND timestamp <= ?"
                    params.append(end_date)

                query += " GROUP BY platform"

                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get trade summary: {e}")
            return []

    def export_trades_csv(self, filepath, start_date=None, end_date=None):
        """Export trades to CSV for external verification."""
        import csv
        try:
            trades = self.get_trades(limit=10000, start_date=start_date, end_date=end_date)
            if not trades:
                return False

            with open(filepath, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=trades[0].keys())
                writer.writeheader()
                writer.writerows(trades)
            return True
        except Exception as e:
            logger.error(f"Failed to export trades: {e}")
            return False
