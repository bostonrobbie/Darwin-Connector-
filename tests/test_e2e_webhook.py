
import unittest
import json
import sys
import os
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock dependencies before importing app
sys.modules['MetaTrader5'] = MagicMock()
# Mock entire topstep client to avoid network usage
with patch('src.topstep.client.TopStepClient') as MockTS:
    # We need to import the app AFTER mocking
    from src.mt5.bridge import app, CONFIG

    def setUp(self):
        # Patch CONFIG for the duration of the test
        self.config_patcher = patch.dict('src.mt5.bridge.CONFIG', {'security': {'webhook_secret': 'TEST_SECRET'}})
        self.config_patcher.start()
        
        self.app = app.test_client()
        self.app.testing = True
        self.secret = 'TEST_SECRET'
        
    def tearDown(self):
        self.config_patcher.stop()
        
    @patch('src.mt5.bridge.execute_trade')
    @patch('src.mt5.bridge.alerts') # Mock alerts to prevent network calls
    @patch('src.mt5.bridge.db')     # Mock DB to prevent disk writes
    def test_webhook_buy_flow(self, mock_db, mock_alerts, mock_exec):
        # Setup Mock Execution Result
        mock_exec.return_value = {
            "success": True,
            "order": 12345,
            "executed_price": 100.0,
            "slippage": 0.0
        }
        
        payload = {
            "secret": self.secret,
            "action": "buy",
            "symbol": "NQ1!",
            "volume": 1.0
        }
        
        response = self.app.post('/webhook', 
                                 data=json.dumps(payload),
                                 content_type='application/json')
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        # Verify Bridge Logic called correct internal function
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0][0]
        self.assertEqual(call_args['symbol'], 'NQ1!')
        
    def test_webhook_unauthorized(self):
        payload = {
            "secret": "WRONG_SECRET",
            "action": "buy"
        }
        response = self.app.post('/webhook', 
                                 data=json.dumps(payload),
                                 content_type='application/json')
                                 
        self.assertEqual(response.status_code, 401)

if __name__ == '__main__':
    unittest.main()
