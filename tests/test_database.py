
import unittest
import sqlite3
import os
import sys
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.database import DatabaseManager

class TestDatabase(unittest.TestCase):
    
    def setUp(self):
        self.test_db = 'test_trades.db'
        self.db = DatabaseManager(self.test_db)
        
    def tearDown(self):
        import time
        # Close connection if open? (Manager handles it per call, but let's be safe)
        if hasattr(self, 'db'):
             del self.db # Ensure no object ref holds it
             
        if os.path.exists(self.test_db):
            for i in range(5):
                try:
                    os.remove(self.test_db)
                    break
                except PermissionError:
                    time.sleep(0.1)
            
    def test_init_creates_table(self):
        with sqlite3.connect(self.test_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            self.assertIsNotNone(cursor.fetchone())
            
    def test_log_trade(self):
        data = {'symbol': 'NQ', 'action': 'BUY', 'volume': 1.0}
        self.db.log_trade('TestPlatform', data, 'success', latency_ms=10.5, executed_price=15000.0)
        
        with sqlite3.connect(self.test_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades")
            row = cursor.fetchone()
            
            # Verify data
            # Schema: id, timestamp, platform, symbol, action, volume, status, latency, details, exp, exec, slip
            self.assertEqual(row[2], 'TestPlatform')
            self.assertEqual(row[3], 'NQ')
            self.assertEqual(row[5], 1.0)
            self.assertEqual(row[6], 'success')
            self.assertEqual(row[7], 10.5)
            self.assertEqual(row[10], 15000.0)

if __name__ == '__main__':
    unittest.main()
