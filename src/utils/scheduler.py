"""
Trading Scheduler Module
Handles:
- Hard exit at end of trading day (4:50 PM ET by default)
- Rogue trade protection (stale webhook detection)
- Trading hours validation
"""

import threading
import time
import logging
import json
import os
from datetime import datetime, timedelta

logger = logging.getLogger("Scheduler")

class TradingScheduler:
    def __init__(self, config, close_all_callback):
        """
        Initialize the trading scheduler.

        Args:
            config: The application config dict
            close_all_callback: Function to call to close all positions (takes platform list)
        """
        self.config = config
        self.close_all_callback = close_all_callback
        self.running = False
        self.thread = None
        self.last_exit_date = None  # Track when we last did a hard exit

        # Load settings
        self.trading_hours = config.get('trading_hours', {})
        self.hard_exit_enabled = self.trading_hours.get('hard_exit_enabled', True)
        self.hard_exit_time = self.trading_hours.get('hard_exit_time', '16:50')
        self.timezone_name = self.trading_hours.get('timezone', 'America/New_York')
        self.trading_days = self.trading_hours.get('trading_days',
            ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])

        # Sunday session settings (futures open Sunday 6 PM ET)
        self.sunday_session_enabled = self.trading_hours.get('sunday_session_enabled', True)
        self.sunday_session_start = self.trading_hours.get('sunday_session_start', '18:00')

        # Try to import pytz for timezone handling
        try:
            import pytz
            self.tz = pytz.timezone(self.timezone_name)
            self.use_pytz = True
        except ImportError:
            logger.warning("pytz not installed. Using system local time for scheduling.")
            self.tz = None
            self.use_pytz = False

    def get_current_time(self):
        """Get current time in the configured timezone."""
        if self.use_pytz:
            import pytz
            return datetime.now(self.tz)
        else:
            # Fallback: Assume local time is ET (adjust manually if needed)
            return datetime.now()

    def is_trading_day(self):
        """Check if today is a trading day (includes Sunday evening session)."""
        current = self.get_current_time()
        day_name = current.strftime('%A')

        # Standard trading days (Mon-Fri)
        if day_name in self.trading_days:
            return True

        # Sunday evening session (futures open at 6 PM ET)
        if day_name == 'Sunday' and self.sunday_session_enabled:
            try:
                start_hour, start_minute = map(int, self.sunday_session_start.split(':'))
                current_minutes = current.hour * 60 + current.minute
                start_minutes = start_hour * 60 + start_minute
                if current_minutes >= start_minutes:
                    return True
            except:
                pass

        return False

    def is_hard_exit_day(self):
        """Check if today is a day for hard exit (Mon-Fri only, not Sunday)."""
        current = self.get_current_time()
        day_name = current.strftime('%A')
        # Hard exit only on Mon-Fri, NOT on Sunday (session just started)
        return day_name in self.trading_days

    def should_hard_exit(self):
        """Check if we should execute hard exit now."""
        if not self.hard_exit_enabled:
            return False

        # Only do hard exit Mon-Fri (not Sunday - session just started)
        if not self.is_hard_exit_day():
            return False

        current = self.get_current_time()
        today_date = current.date()

        # Don't exit twice on the same day
        if self.last_exit_date == today_date:
            return False

        # Parse exit time
        try:
            exit_hour, exit_minute = map(int, self.hard_exit_time.split(':'))
        except:
            exit_hour, exit_minute = 16, 50  # Default 4:50 PM

        # Check if we're at or past the exit time
        current_minutes = current.hour * 60 + current.minute
        exit_minutes = exit_hour * 60 + exit_minute

        # Exit window: exactly at exit time (within 1 minute window)
        if current_minutes >= exit_minutes and current_minutes < exit_minutes + 1:
            return True

        return False

    def execute_hard_exit(self):
        """Execute the hard exit - close all positions on all platforms."""
        logger.warning("=" * 50)
        logger.warning("HARD EXIT TRIGGERED - Closing all positions!")
        logger.warning(f"Time: {self.get_current_time().strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.warning("=" * 50)

        try:
            # Call the close all callback for each platform
            platforms = ['MT5', 'TopStep', 'IBKR']
            for platform in platforms:
                try:
                    logger.info(f"Hard Exit: Closing positions on {platform}...")
                    self.close_all_callback(platform)
                except Exception as e:
                    logger.error(f"Hard Exit failed for {platform}: {e}")

            # Mark that we've done exit today
            self.last_exit_date = self.get_current_time().date()
            logger.info("Hard Exit completed successfully.")

        except Exception as e:
            logger.error(f"Hard Exit error: {e}")

    def start(self):
        """Start the scheduler thread."""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.thread.start()
        logger.info(f"Trading Scheduler started. Hard exit at {self.hard_exit_time} ET on {', '.join(self.trading_days)}")

    def stop(self):
        """Stop the scheduler thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

    def _scheduler_loop(self):
        """Main scheduler loop - checks every 30 seconds."""
        while self.running:
            try:
                if self.should_hard_exit():
                    self.execute_hard_exit()
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")

            time.sleep(30)  # Check every 30 seconds


class WebhookValidator:
    """Validates incoming webhooks to prevent rogue/delayed trades."""

    def __init__(self, config):
        self.config = config
        self.max_age_seconds = config.get('security', {}).get('max_webhook_age_seconds', 30)
        self.recent_webhooks = {}  # Track recent webhooks to prevent duplicates
        self.duplicate_window_seconds = 5  # Window to detect duplicate webhooks

    def validate_webhook(self, data, received_at=None):
        """
        Validate a webhook to prevent rogue trades.

        Returns:
            tuple: (is_valid, rejection_reason or None)
        """
        if received_at is None:
            received_at = datetime.now()

        # 1. Check for webhook timestamp (if provided by TradingView)
        webhook_time = data.get('time') or data.get('timestamp') or data.get('timenow')
        if webhook_time:
            try:
                # TradingView sends Unix timestamp in some cases
                if isinstance(webhook_time, (int, float)):
                    webhook_dt = datetime.fromtimestamp(webhook_time)
                else:
                    webhook_dt = datetime.fromisoformat(str(webhook_time).replace('Z', '+00:00'))

                age_seconds = (received_at - webhook_dt).total_seconds()

                if age_seconds > self.max_age_seconds:
                    return False, f"Stale webhook: {age_seconds:.1f}s old (max: {self.max_age_seconds}s)"

                if age_seconds < -60:  # Future timestamp (clock skew tolerance of 60s)
                    return False, f"Future webhook timestamp detected: {age_seconds:.1f}s"

            except Exception as e:
                # If we can't parse the timestamp, log but continue
                logger.warning(f"Could not parse webhook timestamp: {webhook_time} - {e}")

        # 2. Check for duplicate webhooks (same action/symbol within window)
        webhook_key = f"{data.get('action')}_{data.get('symbol')}_{data.get('volume', 0)}"
        current_time = time.time()

        if webhook_key in self.recent_webhooks:
            last_time = self.recent_webhooks[webhook_key]
            if current_time - last_time < self.duplicate_window_seconds:
                return False, f"Duplicate webhook detected within {self.duplicate_window_seconds}s"

        # Record this webhook
        self.recent_webhooks[webhook_key] = current_time

        # Clean up old entries
        self._cleanup_old_webhooks()

        # 3. Basic sanity checks
        action = data.get('action', '').upper()
        if action not in ['BUY', 'SELL', 'CLOSE', 'EXIT', 'FLATTEN']:
            return False, f"Invalid action: {action}"

        symbol = data.get('symbol', '')
        if not symbol:
            return False, "Missing symbol"

        # Volume check (except for close actions)
        if action in ['BUY', 'SELL']:
            volume = data.get('volume', 0)
            try:
                vol = float(volume)
                if vol <= 0:
                    return False, f"Invalid volume: {volume}"
                if vol > 100:  # Sanity check - unusually large
                    return False, f"Suspiciously large volume: {volume}"
            except (ValueError, TypeError):
                return False, f"Invalid volume format: {volume}"

        return True, None

    def _cleanup_old_webhooks(self):
        """Remove old entries from the recent webhooks tracker."""
        current_time = time.time()
        cutoff = current_time - 60  # Keep last 60 seconds

        self.recent_webhooks = {
            k: v for k, v in self.recent_webhooks.items()
            if v > cutoff
        }


def is_broker_paused(config, broker_name):
    """Check if a specific broker is paused."""
    controls = config.get('broker_controls', {})
    key = f"{broker_name.lower()}_paused"
    return controls.get(key, False)


def set_broker_paused(config_path, broker_name, paused):
    """Set the paused state for a broker and save to config."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)

        if 'broker_controls' not in config:
            config['broker_controls'] = {}

        key = f"{broker_name.lower()}_paused"
        config['broker_controls'][key] = paused

        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)

        return True
    except Exception as e:
        logger.error(f"Failed to set broker paused state: {e}")
        return False
