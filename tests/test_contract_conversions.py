"""
Tests for contract/symbol conversion logic across all brokers.
Ensures consistent position sizing for MT5, TopStep, and IBKR.
"""

import unittest
import sys
import os

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.conversions import ContractConverter


class TestMT5Conversions(unittest.TestCase):
    """Tests for MT5 symbol/volume conversions."""

    def setUp(self):
        self.config = {
            'mt5': {
                'symbol_map': {
                    'NQ1!': {'name': 'NQ_SEP25', 'multiplier': 1.0},
                    'ES1!': {'name': 'ES_SEP25', 'multiplier': 1.0},
                    'EURUSD': 'EURUSD.raw'
                }
            }
        }
        self.converter = ContractConverter(self.config)

    def test_mt5_symbol_mapping_dict(self):
        symbol, volume = self.converter.convert_for_mt5('NQ1!', 1.0)
        self.assertEqual(symbol, 'NQ_SEP25')
        self.assertEqual(volume, 1.0)

    def test_mt5_symbol_mapping_string(self):
        symbol, volume = self.converter.convert_for_mt5('EURUSD', 1.0)
        self.assertEqual(symbol, 'EURUSD.raw')
        self.assertEqual(volume, 1.0)

    def test_mt5_multiplier_applied(self):
        config = {'mt5': {'symbol_map': {'NQ1!': {'name': 'MNQ_SEP25', 'multiplier': 5.0}}}}
        converter = ContractConverter(config)
        symbol, volume = converter.convert_for_mt5('NQ1!', 2.0)
        self.assertEqual(symbol, 'MNQ_SEP25')
        self.assertEqual(volume, 10.0)

    def test_mt5_unmapped_symbol_passthrough(self):
        symbol, volume = self.converter.convert_for_mt5('UNKNOWN', 1.5)
        self.assertEqual(symbol, 'UNKNOWN')
        self.assertEqual(volume, 1.5)


class TestTopStepConversions(unittest.TestCase):
    """Tests for TopStep symbol/volume conversions."""

    def setUp(self):
        self.config = {'topstep': {'micros_per_mini': 5, 'max_micros': 15}}
        self.converter = ContractConverter(self.config)

    def test_topstep_nq_to_mnq(self):
        symbol, volume = self.converter.convert_for_topstep('NQ1!', 1.0)
        self.assertEqual(symbol, 'MNQ')

    def test_topstep_es_to_mes(self):
        symbol, volume = self.converter.convert_for_topstep('ES1!', 1.0)
        self.assertEqual(symbol, 'MES')

    def test_topstep_micro_conversion(self):
        symbol, volume = self.converter.convert_for_topstep('NQ1!', 1.0)
        self.assertEqual(volume, 5)

    def test_topstep_max_cap(self):
        symbol, volume = self.converter.convert_for_topstep('NQ1!', 10.0)
        self.assertEqual(volume, 15)

    def test_topstep_minimum_1_contract(self):
        symbol, volume = self.converter.convert_for_topstep('NQ1!', 0.1)
        self.assertEqual(volume, 1)


class TestIBKRConversions(unittest.TestCase):
    """Tests for IBKR symbol/volume conversions."""

    def setUp(self):
        self.config = {
            'ibkr': {
                'symbol_map': {'NQ': 'MNQ', 'ES': 'MES', 'NQ1!': 'MNQ', 'ES1!': 'MES'},
                'position_sizing': {'micros_per_mini': 1, 'max_micros': 3}
            }
        }
        self.converter = ContractConverter(self.config)

    def test_ibkr_nq_to_mnq(self):
        symbol, volume = self.converter.convert_for_ibkr('NQ1!', 1.0)
        self.assertEqual(symbol, 'MNQ')

    def test_ibkr_max_cap(self):
        symbol, volume = self.converter.convert_for_ibkr('NQ1!', 10.0)
        self.assertEqual(volume, 3)

    def test_ibkr_minimum_1_contract(self):
        symbol, volume = self.converter.convert_for_ibkr('NQ1!', 0.1)
        self.assertEqual(volume, 1)


class TestConvertAll(unittest.TestCase):
    """Tests for convert_all method."""

    def setUp(self):
        self.config = {
            'mt5': {'symbol_map': {'NQ1!': {'name': 'NQ_SEP25', 'multiplier': 1.0}}},
            'topstep': {'micros_per_mini': 5, 'max_micros': 15},
            'ibkr': {'symbol_map': {'NQ1!': 'MNQ', 'NQ': 'MNQ'}, 'position_sizing': {'micros_per_mini': 1, 'max_micros': 3}}
        }
        self.converter = ContractConverter(self.config)

    def test_convert_all_returns_all_brokers(self):
        result = self.converter.convert_all('NQ1!', 2.0)
        self.assertIn('mt5', result)
        self.assertIn('topstep', result)
        self.assertIn('ibkr', result)

    def test_convert_all_correct_values(self):
        result = self.converter.convert_all('NQ1!', 2.0)
        self.assertEqual(result['mt5']['symbol'], 'NQ_SEP25')
        self.assertEqual(result['topstep']['volume'], 10)
        self.assertEqual(result['ibkr']['volume'], 2)


class TestStaticMethods(unittest.TestCase):
    """Tests for static utility methods."""

    def test_clean_tradingview_symbol(self):
        self.assertEqual(ContractConverter.clean_tradingview_symbol('NQ1!'), 'NQ')
        self.assertEqual(ContractConverter.clean_tradingview_symbol('ES2!'), 'ES')

    def test_is_futures_symbol(self):
        self.assertTrue(ContractConverter.is_futures_symbol('NQ1!'))
        self.assertTrue(ContractConverter.is_futures_symbol('MNQ'))
        self.assertFalse(ContractConverter.is_futures_symbol('EURUSD'))


if __name__ == '__main__':
    unittest.main()
