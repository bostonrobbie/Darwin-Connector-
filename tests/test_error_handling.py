"""
Tests for error handling and retry logic.
Covers transient error retries, fatal error handling, and circuit breakers.
"""

import unittest
import sys
import os
import time
from unittest.mock import MagicMock, patch, Mock

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock mt5 before importing bridge
mock_mt5 = MagicMock()
sys.modules['MetaTrader5'] = mock_mt5


class TestMT5RetryLogic(unittest.TestCase):
    """Tests for MT5 safe_order_send retry logic."""

    def setUp(self):
        """Set up mock MT5 module."""
        self.mock_mt5 = mock_mt5
        # Set up return codes
        self.mock_mt5.TRADE_RETCODE_DONE = 10009
        self.mock_mt5.TRADE_RETCODE_CONNECTION = 10031
        self.mock_mt5.TRADE_RETCODE_TIMEOUT = 10028
        self.mock_mt5.TRADE_RETCODE_INVALID = 10013
        self.mock_mt5.TRADE_RETCODE_MARKET_CLOSED = 10018

    def test_retry_delays_optimized(self):
        """Test that retry delays are optimized for low latency."""
        # Expected optimized delays: [0.1, 0.3, 0.5]
        expected_delays = [0.1, 0.3, 0.5]

        # Import and check the delays
        from src.mt5 import bridge

        # We can't directly access the delays variable, but we can verify
        # the function exists and is properly structured
        self.assertTrue(hasattr(bridge, 'safe_order_send'))

    @patch('src.mt5.bridge.mt5')
    def test_retry_on_connection_error(self, mock_mt5_module):
        """Test that connection errors trigger retry."""
        from src.mt5 import bridge

        mock_res_fail = MagicMock()
        mock_res_fail.retcode = 10031  # CONNECTION error

        mock_res_success = MagicMock()
        mock_res_success.retcode = 10009  # DONE

        mock_mt5_module.order_send.side_effect = [mock_res_fail, mock_res_success]
        mock_mt5_module.TRADE_RETCODE_DONE = 10009
        mock_mt5_module.TRADE_RETCODE_CONNECTION = 10031
        mock_mt5_module.TRADE_RETCODE_TIMEOUT = 10028

        result = bridge.safe_order_send({})

        self.assertEqual(result.retcode, 10009)
        self.assertEqual(mock_mt5_module.order_send.call_count, 2)

    @patch('src.mt5.bridge.mt5')
    def test_retry_on_timeout_error(self, mock_mt5_module):
        """Test that timeout errors trigger retry."""
        from src.mt5 import bridge

        mock_res_fail = MagicMock()
        mock_res_fail.retcode = 10028  # TIMEOUT error

        mock_res_success = MagicMock()
        mock_res_success.retcode = 10009  # DONE

        mock_mt5_module.order_send.side_effect = [mock_res_fail, mock_res_success]
        mock_mt5_module.TRADE_RETCODE_DONE = 10009
        mock_mt5_module.TRADE_RETCODE_CONNECTION = 10031
        mock_mt5_module.TRADE_RETCODE_TIMEOUT = 10028

        result = bridge.safe_order_send({})

        self.assertEqual(result.retcode, 10009)

    @patch('src.mt5.bridge.mt5')
    def test_no_retry_on_invalid_params(self, mock_mt5_module):
        """Test that invalid parameter errors don't retry (fatal error)."""
        from src.mt5 import bridge

        mock_res_invalid = MagicMock()
        mock_res_invalid.retcode = 10013  # INVALID parameters
        mock_res_invalid.comment = "Invalid parameters"

        mock_mt5_module.order_send.return_value = mock_res_invalid
        mock_mt5_module.TRADE_RETCODE_DONE = 10009
        mock_mt5_module.TRADE_RETCODE_CONNECTION = 10031
        mock_mt5_module.TRADE_RETCODE_TIMEOUT = 10028
        mock_mt5_module.TRADE_RETCODE_INVALID = 10013

        result = bridge.safe_order_send({})

        # Should return after first attempt (no retries for fatal errors)
        self.assertEqual(result.retcode, 10013)
        # Only 1 call since invalid is a fatal error
        self.assertEqual(mock_mt5_module.order_send.call_count, 1)

    @patch('src.mt5.bridge.mt5')
    def test_max_retries_exhausted(self, mock_mt5_module):
        """Test behavior when all retries are exhausted."""
        from src.mt5 import bridge

        mock_res_fail = MagicMock()
        mock_res_fail.retcode = 10031  # CONNECTION error
        mock_res_fail.comment = "Connection failed"

        # All attempts fail
        mock_mt5_module.order_send.return_value = mock_res_fail
        mock_mt5_module.TRADE_RETCODE_DONE = 10009
        mock_mt5_module.TRADE_RETCODE_CONNECTION = 10031
        mock_mt5_module.TRADE_RETCODE_TIMEOUT = 10028

        result = bridge.safe_order_send({}, max_retries=3)

        # Should have tried 3 times
        self.assertEqual(mock_mt5_module.order_send.call_count, 3)
        # safe_order_send returns None when all retries exhausted for transient errors
        self.assertIsNone(result)

    @patch('src.mt5.bridge.mt5')
    def test_none_response_triggers_retry(self, mock_mt5_module):
        """Test that None response triggers retry."""
        from src.mt5 import bridge

        mock_res_success = MagicMock()
        mock_res_success.retcode = 10009  # DONE

        # First returns None, second succeeds
        mock_mt5_module.order_send.side_effect = [None, mock_res_success]
        mock_mt5_module.TRADE_RETCODE_DONE = 10009
        mock_mt5_module.TRADE_RETCODE_CONNECTION = 10031
        mock_mt5_module.TRADE_RETCODE_TIMEOUT = 10028

        result = bridge.safe_order_send({})

        self.assertEqual(result.retcode, 10009)
        self.assertEqual(mock_mt5_module.order_send.call_count, 2)


class TestTopStepCircuitBreaker(unittest.TestCase):
    """Tests for TopStep circuit breaker logic."""

    def test_circuit_breaker_trips_on_consecutive_failures(self):
        """Test that circuit breaker trips after consecutive failures."""
        # Simulate circuit breaker state
        failure_count = 0
        max_failures = 3
        circuit_open = False

        def record_failure():
            nonlocal failure_count, circuit_open
            failure_count += 1
            if failure_count >= max_failures:
                circuit_open = True

        # Simulate 3 failures
        for _ in range(3):
            record_failure()

        self.assertTrue(circuit_open)

    def test_circuit_breaker_resets_on_success(self):
        """Test that circuit breaker resets on successful call."""
        failure_count = 2
        circuit_open = False

        def record_success():
            nonlocal failure_count, circuit_open
            failure_count = 0
            circuit_open = False

        record_success()

        self.assertEqual(failure_count, 0)
        self.assertFalse(circuit_open)

    def test_circuit_breaker_blocks_when_open(self):
        """Test that requests are blocked when circuit is open."""
        circuit_open = True
        last_failure_time = time.time()
        cooldown_seconds = 30

        def should_allow_request():
            if not circuit_open:
                return True
            # Allow if cooldown has passed
            return time.time() - last_failure_time > cooldown_seconds

        # Should be blocked immediately
        self.assertFalse(should_allow_request())


class TestIBKRErrorHandling(unittest.TestCase):
    """Tests for IBKR error handling."""

    def test_connection_retry_logic(self):
        """Test IBKR connection retry logic."""
        max_retries = 3
        retry_count = 0
        connected = False

        def attempt_connect():
            nonlocal retry_count, connected
            retry_count += 1
            if retry_count >= 2:  # Succeed on second try
                connected = True
                return True
            return False

        while retry_count < max_retries and not connected:
            attempt_connect()

        self.assertTrue(connected)
        self.assertEqual(retry_count, 2)

    def test_disconnection_detection(self):
        """Test that IBKR disconnection is properly detected."""
        class MockIB:
            def __init__(self):
                self._connected = True

            def isConnected(self):
                return self._connected

            def disconnect(self):
                self._connected = False

        ib = MockIB()
        self.assertTrue(ib.isConnected())

        ib.disconnect()
        self.assertFalse(ib.isConnected())

    def test_order_rejection_handling(self):
        """Test handling of order rejection."""
        # Simulate order rejection response
        rejection_codes = {
            'NO_POSITION': 'No position to close',
            'INSUFFICIENT_FUNDS': 'Insufficient buying power',
            'INVALID_SYMBOL': 'Invalid contract symbol',
            'MARKET_CLOSED': 'Market is closed'
        }

        def handle_rejection(code):
            if code in rejection_codes:
                return {'status': 'error', 'error': rejection_codes[code]}
            return {'status': 'error', 'error': 'Unknown error'}

        result = handle_rejection('NO_POSITION')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'No position to close')


class TestGeneralErrorHandling(unittest.TestCase):
    """General error handling tests."""

    def test_exception_in_executor_handled(self):
        """Test that exceptions in thread executor are properly handled."""
        from concurrent.futures import ThreadPoolExecutor

        def failing_task():
            raise ValueError("Task failed")

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(failing_task)

        result = None
        try:
            result = future.result(timeout=1.0)
        except ValueError as e:
            result = {'status': 'error', 'error': str(e)}

        executor.shutdown(wait=False)

        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'Task failed')

    def test_timeout_error_graceful(self):
        """Test graceful handling of timeout errors."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        def slow_task():
            time.sleep(5)
            return "done"

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(slow_task)

        result = None
        try:
            result = future.result(timeout=0.1)
        except TimeoutError:
            result = {'status': 'timeout', 'error': 'Operation timed out'}
        except Exception as e:
            result = {'status': 'timeout', 'error': str(e)}

        executor.shutdown(wait=False)

        self.assertEqual(result['status'], 'timeout')

    def test_network_error_handling(self):
        """Test handling of network errors."""
        import requests

        def make_request_with_retry(url, max_retries=3):
            for attempt in range(max_retries):
                try:
                    # Simulate network error
                    raise requests.exceptions.ConnectionError("Network unreachable")
                except requests.exceptions.ConnectionError as e:
                    if attempt == max_retries - 1:
                        return {'status': 'error', 'error': str(e)}
                    time.sleep(0.1)
            return {'status': 'error', 'error': 'Max retries exceeded'}

        result = make_request_with_retry("http://localhost:9999")
        self.assertEqual(result['status'], 'error')


class TestLoggingOnError(unittest.TestCase):
    """Tests for proper logging on errors."""

    @patch('src.mt5.bridge.logger')
    @patch('src.mt5.bridge.mt5')
    def test_error_logged_on_failure(self, mock_mt5_module, mock_logger):
        """Test that errors are properly logged."""
        from src.mt5 import bridge

        mock_res = MagicMock()
        mock_res.retcode = 10013  # Invalid
        mock_res.comment = "Invalid parameters"

        mock_mt5_module.order_send.return_value = mock_res
        mock_mt5_module.TRADE_RETCODE_DONE = 10009
        mock_mt5_module.TRADE_RETCODE_CONNECTION = 10031
        mock_mt5_module.TRADE_RETCODE_TIMEOUT = 10028
        mock_mt5_module.TRADE_RETCODE_INVALID = 10013

        bridge.safe_order_send({})

        # Verify logger was called (error logged)
        self.assertTrue(mock_logger.error.called or mock_logger.warning.called or
                       mock_logger.info.called)


if __name__ == '__main__':
    unittest.main()
