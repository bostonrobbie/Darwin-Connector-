"""
Tests for webhook validation logic.
Covers stale webhook rejection, duplicate detection, and field validation.
"""

import unittest
import sys
import os
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.scheduler import WebhookValidator


class TestWebhookValidation(unittest.TestCase):
    """Tests for WebhookValidator class."""

    def setUp(self):
        """Set up test config for each test."""
        self.config = {
            'security': {
                'webhook_secret': 'test_secret',
                'max_webhook_age_seconds': 30
            }
        }
        self.validator = WebhookValidator(self.config)

    def test_valid_webhook(self):
        """Test that a valid webhook passes validation."""
        data = {
            'action': 'BUY',
            'symbol': 'NQ1!',
            'volume': 1.0,
            'timestamp': time.time()  # Current time
        }
        is_valid, reason = self.validator.validate_webhook(data)
        self.assertTrue(is_valid)
        self.assertIsNone(reason)

    def test_valid_webhook_no_timestamp(self):
        """Test that a webhook without timestamp passes (backwards compatible)."""
        data = {
            'action': 'BUY',
            'symbol': 'NQ1!',
            'volume': 1.0
        }
        is_valid, reason = self.validator.validate_webhook(data)
        self.assertTrue(is_valid)
        self.assertIsNone(reason)

    def test_stale_webhook_rejected(self):
        """Test that webhooks older than 30s are rejected."""
        stale_time = time.time() - 60  # 60 seconds ago
        data = {
            'action': 'BUY',
            'symbol': 'NQ1!',
            'volume': 1.0,
            'timestamp': stale_time
        }
        is_valid, reason = self.validator.validate_webhook(data)
        self.assertFalse(is_valid)
        self.assertIn('Stale webhook', reason)

    def test_future_webhook_rejected(self):
        """Test that webhooks with future timestamps (>60s) are rejected."""
        future_time = time.time() + 120  # 2 minutes in future
        data = {
            'action': 'BUY',
            'symbol': 'NQ1!',
            'volume': 1.0,
            'timestamp': future_time
        }
        is_valid, reason = self.validator.validate_webhook(data)
        self.assertFalse(is_valid)
        self.assertIn('Future webhook', reason)

    def test_duplicate_webhook_rejected(self):
        """Test that duplicate webhooks within 5s window are rejected."""
        data = {
            'action': 'BUY',
            'symbol': 'NQ1!',
            'volume': 1.0
        }
        # First webhook should pass
        is_valid1, reason1 = self.validator.validate_webhook(data)
        self.assertTrue(is_valid1)

        # Same webhook immediately after should fail
        is_valid2, reason2 = self.validator.validate_webhook(data)
        self.assertFalse(is_valid2)
        self.assertIn('Duplicate webhook', reason2)

    def test_different_webhook_after_duplicate(self):
        """Test that different webhooks pass even after a duplicate rejection."""
        data1 = {
            'action': 'BUY',
            'symbol': 'NQ1!',
            'volume': 1.0
        }
        data2 = {
            'action': 'SELL',
            'symbol': 'NQ1!',
            'volume': 1.0
        }
        # First BUY
        is_valid1, _ = self.validator.validate_webhook(data1)
        self.assertTrue(is_valid1)

        # SELL should still pass (different action)
        is_valid2, _ = self.validator.validate_webhook(data2)
        self.assertTrue(is_valid2)

    def test_different_symbol_not_duplicate(self):
        """Test that same action on different symbol is not a duplicate."""
        data1 = {
            'action': 'BUY',
            'symbol': 'NQ1!',
            'volume': 1.0
        }
        data2 = {
            'action': 'BUY',
            'symbol': 'ES1!',
            'volume': 1.0
        }
        is_valid1, _ = self.validator.validate_webhook(data1)
        self.assertTrue(is_valid1)

        is_valid2, _ = self.validator.validate_webhook(data2)
        self.assertTrue(is_valid2)

    def test_custom_max_age(self):
        """Test that custom max_webhook_age_seconds is respected."""
        config = {
            'security': {
                'max_webhook_age_seconds': 10  # Shorter window
            }
        }
        validator = WebhookValidator(config)

        # 15 seconds old should fail with 10s max
        data = {
            'action': 'BUY',
            'symbol': 'NQ1!',
            'volume': 1.0,
            'timestamp': time.time() - 15
        }
        is_valid, reason = validator.validate_webhook(data)
        self.assertFalse(is_valid)
        self.assertIn('Stale webhook', reason)


if __name__ == '__main__':
    unittest.main()
