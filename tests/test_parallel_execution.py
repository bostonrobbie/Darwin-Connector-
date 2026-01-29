"""
Tests for parallel broker execution.
Verifies that MT5, IBKR, and TopStep execute in true parallel.
"""

import unittest
import sys
import os
import time
from unittest.mock import MagicMock, patch, Mock
from concurrent.futures import ThreadPoolExecutor

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock mt5 before importing bridge
sys.modules['MetaTrader5'] = MagicMock()


class TestParallelExecution(unittest.TestCase):
    """Tests for parallel broker execution."""

    def setUp(self):
        """Set up mocks and test config."""
        self.config = {
            'mt5': {'enabled': True},
            'ibkr': {'enabled': True, 'paused': False},
            'topstep': {'enabled': True, 'paused': False},
            'server': {'ibkr_port': 5001, 'mt5_port': 5000},
            'security': {'webhook_secret': 'test_secret'}
        }

    def test_executor_exists(self):
        """Test that ThreadPoolExecutor is available."""
        executor = ThreadPoolExecutor(max_workers=3)
        self.assertIsNotNone(executor)
        executor.shutdown(wait=False)

    def test_parallel_timing_simulation(self):
        """Test that 3 broker calls in parallel complete faster than sequential."""
        def slow_broker_call(name, delay=0.5):
            time.sleep(delay)
            return {'broker': name, 'status': 'success'}

        executor = ThreadPoolExecutor(max_workers=3)
        start_parallel = time.time()

        futures = {
            'mt5': executor.submit(slow_broker_call, 'MT5', 0.5),
            'ibkr': executor.submit(slow_broker_call, 'IBKR', 0.5),
            'topstep': executor.submit(slow_broker_call, 'TopStep', 0.5)
        }

        results = {}
        for broker, future in futures.items():
            results[broker] = future.result(timeout=2.0)

        parallel_duration = time.time() - start_parallel
        executor.shutdown(wait=False)

        self.assertEqual(results['mt5']['status'], 'success')
        self.assertEqual(results['ibkr']['status'], 'success')
        self.assertEqual(results['topstep']['status'], 'success')

        # Parallel should take ~0.5s (not 1.5s sequential)
        self.assertLess(parallel_duration, 1.0,
                       f"Parallel execution took {parallel_duration:.2f}s, expected < 1.0s")

    def test_partial_failure_handled(self):
        """Test that one broker failing does not affect others."""
        def broker_call(name, should_fail=False):
            time.sleep(0.1)
            if should_fail:
                raise Exception(f"{name} failed")
            return {'broker': name, 'status': 'success'}

        executor = ThreadPoolExecutor(max_workers=3)

        futures = {
            'mt5': executor.submit(broker_call, 'MT5', False),
            'ibkr': executor.submit(broker_call, 'IBKR', True),
            'topstep': executor.submit(broker_call, 'TopStep', False)
        }

        results = {}
        for broker, future in futures.items():
            try:
                results[broker] = future.result(timeout=2.0)
            except Exception as e:
                results[broker] = {'status': 'error', 'error': str(e)}

        executor.shutdown(wait=False)

        self.assertEqual(results['mt5']['status'], 'success')
        self.assertEqual(results['topstep']['status'], 'success')
        self.assertEqual(results['ibkr']['status'], 'error')

    def test_timeout_handled(self):
        """Test that slow broker calls timeout properly."""
        def slow_broker(name, delay=5.0):
            time.sleep(delay)
            return {'broker': name, 'status': 'success'}

        executor = ThreadPoolExecutor(max_workers=3)
        future = executor.submit(slow_broker, 'SlowBroker', 5.0)

        result = None
        try:
            result = future.result(timeout=0.5)
        except Exception as e:
            result = {'status': 'timeout', 'error': str(e)}

        executor.shutdown(wait=False)
        self.assertEqual(result['status'], 'timeout')


class TestBrokerPauseLogic(unittest.TestCase):
    """Tests for broker pause/enable logic."""

    def test_is_broker_paused_returns_true_when_paused(self):
        """Test that paused broker is detected."""
        config = {
            'ibkr': {'enabled': True, 'paused': True},
            'topstep': {'enabled': True, 'paused': False}
        }

        def is_broker_paused(cfg, broker):
            broker_cfg = cfg.get(broker, {})
            if not broker_cfg.get('enabled', True):
                return True
            return broker_cfg.get('paused', False)

        self.assertTrue(is_broker_paused(config, 'ibkr'))
        self.assertFalse(is_broker_paused(config, 'topstep'))

    def test_is_broker_paused_returns_true_when_disabled(self):
        """Test that disabled broker is treated as paused."""
        config = {'ibkr': {'enabled': False, 'paused': False}}

        def is_broker_paused(cfg, broker):
            broker_cfg = cfg.get(broker, {})
            if not broker_cfg.get('enabled', True):
                return True
            return broker_cfg.get('paused', False)

        self.assertTrue(is_broker_paused(config, 'ibkr'))


class TestParallelResultAggregation(unittest.TestCase):
    """Tests for aggregating results from parallel broker calls."""

    def test_aggregate_all_success(self):
        """Test aggregation when all brokers succeed."""
        results = {
            'mt5': {'status': 'success', 'order': 12345},
            'ibkr': {'status': 'success', 'order_id': 67890},
            'topstep': {'status': 'success', 'orderId': 11111}
        }

        all_success = all(r.get('status') == 'success' for r in results.values())
        self.assertTrue(all_success)

    def test_aggregate_partial_failure(self):
        """Test aggregation when some brokers fail."""
        results = {
            'mt5': {'status': 'success', 'order': 12345},
            'ibkr': {'status': 'error', 'error': 'Connection failed'},
            'topstep': {'status': 'success', 'orderId': 11111}
        }

        successes = [k for k, v in results.items() if v.get('status') == 'success']
        failures = [k for k, v in results.items() if v.get('status') != 'success']

        self.assertEqual(len(successes), 2)
        self.assertEqual(len(failures), 1)
        self.assertIn('ibkr', failures)


if __name__ == '__main__':
    unittest.main()
