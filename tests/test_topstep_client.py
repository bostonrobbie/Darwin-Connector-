
import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.topstep.client import TopStepClient

class TestTopStepClient(unittest.TestCase):
    
    def setUp(self):
        self.config = {
            'topstep': {
                'enabled': True,
                'mock_mode': False,
                'api_key': 'test_key',
                'base_url': 'https://test.api',
                'max_retries': 2
            }
        }
        self.client = TopStepClient(self.config)
        
    @patch('src.topstep.client.requests.Session')
    def test_execute_trade_sends_limit_params(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orderId": 123}
        mock_session.post.return_value = mock_response
        self.client.session = mock_session
        
        data = {
            "symbol": "MNQ", 
            "action": "BUY", 
            "volume": 1.0, 
            "price": 15000.0,
            "sl": 14900.0,
            "tp": 15100.0
        }
        res = self.client.execute_trade(data)
        
        self.assertEqual(res['status'], 'success')
        
        # Verify Payload
        args, kwargs = mock_session.post.call_args
        payload = kwargs['json']
        
        self.assertEqual(payload['orderType'], 'LIMIT')
        self.assertEqual(payload['price'], 15000.0)
        self.assertEqual(payload['bracket']['stopLossPrice'], 14900.0)
        self.assertEqual(payload['bracket']['takeProfitPrice'], 15100.0)

if __name__ == '__main__':
    unittest.main()
