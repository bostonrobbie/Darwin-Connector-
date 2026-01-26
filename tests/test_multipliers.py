import unittest
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

class TestMultipliers(unittest.TestCase):
    def setUp(self):
        # Mock Config
        self.config_map = {
            "NQ": "MNQ",
            "MNQ": "MNQ",
            "ES": "MES"
        }
        
    def test_nq_multiplier(self):
        """Test Case 1: 1 NQ -> 7 MNQ"""
        # Logic extracted from planned implementation
        input_symbol = "NQ"
        input_volume = 1.0
        
        target_symbol, target_volume = self.apply_logic(input_symbol, input_volume)
        
        self.assertEqual(target_symbol, "MNQ")
        self.assertEqual(target_volume, 7.0)
        
    def test_nq_multiplier_sell(self):
        """Test Case 2: 2 NQ -> 14 MNQ"""
        input_symbol = "NQ"
        input_volume = 2.0
        
        target_symbol, target_volume = self.apply_logic(input_symbol, input_volume)
        
        self.assertEqual(target_symbol, "MNQ")
        self.assertEqual(target_volume, 14.0)

    def test_es_multiplier(self):
        """Test Case 3: 1 ES -> 1 MES (No 7x multiplier for ES)"""
        input_symbol = "ES"
        input_volume = 1.0
        
        # Hypothetical logic: Only NQ gets the 7x? Or ES too?
        # User request said: "trade 7 micros on MNQ" (specifically for NQ)
        # We assume ES is just 1:1 or standard mapping (e.g. 1 ES -> 10 MES if we wanted equal notional, but user didn't ask)
        # The user specifically said: "convert all trades into the right position sizing that we defined"
        # AND "For NQ... trade 7 micros".
        # I will assume ONLY NQ gets 7x for now, others get 1x or direct map
        
        target_symbol, target_volume = self.apply_logic(input_symbol, input_volume)
        
        self.assertEqual(target_symbol, "MES")
        self.assertEqual(target_volume, 1.0) # Default 1x

    def apply_logic(self, symbol, volume):
        """
        The EXACT logic we plan to inject into bridge.py
        """
        target = self.config_map.get(symbol, symbol)
        multiplier = 1.0
        
        if symbol == "NQ":
            multiplier = 7.0
            
        return target, volume * multiplier

if __name__ == '__main__':
    unittest.main()
