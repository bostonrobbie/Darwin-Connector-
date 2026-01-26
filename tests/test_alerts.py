
import unittest
import sys
import os
import time
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.alerts import AlertManager

class TestAlerts(unittest.TestCase):
    
    def setUp(self):
        self.config = {
            'alerts': {
                'enabled': True,
                'discord_webhook': 'https://discord.com/api/webhooks/fake'
            }
        }
        self.alerts = AlertManager(self.config)
        
    @patch('src.utils.alerts.requests.post')
    def test_send_trade_alert(self, mock_post):
        trade_data = {'symbol': 'NQ', 'action': 'BUY', 'volume': 1.0}
        self.alerts.send_trade_alert(trade_data, platform="Test")
        
        # Alert sends in a thread, so we wait briefly
        time.sleep(0.1)
        
        # Alerts are now DISABLED. Expect NO call.
        mock_post.assert_not_called()

if __name__ == '__main__':
    unittest.main()
