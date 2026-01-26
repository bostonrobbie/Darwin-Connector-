
import unittest
import sys
import os
import time
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock mt5 before importing bridge
sys.modules['MetaTrader5'] = MagicMock()

from src.mt5 import bridge

class TestMT5BridgeRobustness(unittest.TestCase):
    
    def setUp(self):
        # Reset config
        bridge.CONFIG = {
            'mt5': {
                'path': 'mock_path',
                'login': 12345,
                'password': 'pass',
                'server': 'demo',
                'magic_number': 123,
                'execution': {
                    'default_type': 'LIMIT', 
                    'slippage_offset_ticks': 2,
                    'default_sl_ticks': 10,
                    'default_tp_ticks': 20
                }
            },
            'topstep': {'enabled': False},
            'security': {'webhook_secret': 'secret'}
        }
        bridge.MT5_CONF = bridge.CONFIG['mt5']
        
    @patch('src.mt5.bridge.mt5')
    def test_validate_terminal_state_success(self, mock_mt5):
        mock_mt5.terminal_info.return_value = True
        self.assertTrue(bridge.validate_terminal_state())
        
    @patch('src.mt5.bridge.mt5')
    def test_validate_terminal_state_reconnect(self, mock_mt5):
        # Fail first, Success second
        mock_mt5.terminal_info.side_effect = [None, True] 
        mock_mt5.initialize.return_value = True
        mock_mt5.login.return_value = True
        
        self.assertTrue(bridge.validate_terminal_state())
        mock_mt5.initialize.assert_called()

    @patch('src.mt5.bridge.mt5')
    def test_safe_order_send_retry(self, mock_mt5):
        # Fail transiently twice, then success
        mock_res_fail = MagicMock()
        mock_res_fail.retcode = mock_mt5.TRADE_RETCODE_CONNECTION
        
        mock_res_success = MagicMock()
        mock_res_success.retcode = mock_mt5.TRADE_RETCODE_DONE
        
        mock_mt5.order_send.side_effect = [mock_res_fail, mock_res_fail, mock_res_success]
        
        req = {}
        res = bridge.safe_order_send(req)
        
        self.assertEqual(res.retcode, mock_mt5.TRADE_RETCODE_DONE)
        self.assertEqual(mock_mt5.order_send.call_count, 3)

    @patch('src.mt5.bridge.mt5')
    def test_execute_trade_forces_limit_and_sl_tp(self, mock_mt5):
        # Mock Ticks
        mock_tick = MagicMock()
        mock_tick.ask = 100.0
        mock_mt5.symbol_info_tick.return_value = mock_tick
        
        mock_info = MagicMock()
        mock_info.point = 0.5
        mock_mt5.symbol_info.return_value = mock_info
        
        mock_res = MagicMock()
        mock_res.retcode = mock_mt5.TRADE_RETCODE_DONE
        mock_res.price = 101.0
        mock_mt5.order_send.return_value = mock_res
        
        # Test Data (MARKET requested, NO SL/TP provided)
        data = {'action': 'BUY', 'symbol': 'NQ', 'volume': 1.0, 'type': 'MARKET'}
        
        res = bridge.execute_trade(data)
        self.assertTrue(res['success'])
        
        # Verify LIMIT enforcement
        args, _ = mock_mt5.order_send.call_args
        req = args[0]
        self.assertEqual(req['type'], mock_mt5.ORDER_TYPE_BUY_LIMIT)
        
        # Verify Price Calculation (Ask + 2 ticks)
        # 100 + (2 * 0.5) = 101.0
        self.assertEqual(req['price'], 101.0)
        
        # Verify SL/TP Calculation (No Defaults requested)
        self.assertEqual(req['sl'], 0.0)
        self.assertEqual(req['tp'], 0.0)

if __name__ == '__main__':
    unittest.main()
