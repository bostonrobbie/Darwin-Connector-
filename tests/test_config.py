
import unittest
import json
import os
import sys

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestConfig(unittest.TestCase):
    
    def setUp(self):
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
        
    def test_config_exists(self):
        self.assertTrue(os.path.exists(self.config_path), "config.json not found")
        
    def test_config_structure(self):
        with open(self.config_path, 'r') as f:
            config = json.load(f)
            
        required_sections = ['mt5', 'server', 'security']
        for section in required_sections:
            self.assertIn(section, config, f"Missing section: {section}")
            
    def test_mt5_config_valid(self):
        with open(self.config_path, 'r') as f:
            config = json.load(f)
        
        mt5_conf = config.get('mt5', {})
        self.assertTrue(mt5_conf.get('path'), "MT5 Path missing")
        self.assertTrue(mt5_conf.get('login'), "MT5 Login missing")
        self.assertTrue(mt5_conf.get('server'), "MT5 Server missing")
        
    def test_security_valid(self):
        with open(self.config_path, 'r') as f:
            config = json.load(f)
            
        self.assertTrue(config.get('security', {}).get('webhook_secret'), "Webhook Secret is empty!")

if __name__ == '__main__':
    unittest.main()
