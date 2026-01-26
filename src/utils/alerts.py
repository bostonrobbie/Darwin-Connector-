import requests
import json
import logging
import threading
from datetime import datetime

logger = logging.getLogger("Alerts")

class AlertManager:
    def __init__(self, config):
        self.config = config.get('alerts', {})
        self.enabled = self.config.get('enabled', False)
        self.webhook_url = self.config.get('discord_webhook', '')

    def send_trade_alert(self, trade_data, platform="Unknown", status="Executed"):
        """Alerts disabled by user request."""
        pass

    def send_error_alert(self, error_msg, context="System"):
        """Sends a critical error alert."""
        if not self.enabled or not self.webhook_url:
            return

        embed = {
            "title": f"🚨 CRITICAL ERROR ({context})",
            "description": f"```{error_msg}```",
            "color": 15548997, # Red
            "timestamp": datetime.now().isoformat()
        }
        self._post_async(embed)

    def _post_async(self, embed):
        """Fire and forget execution to not block main thread."""
        def _send():
            try:
                payload = {"embeds": [embed]}
                requests.post(self.webhook_url, json=payload, timeout=5)
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")
        
        threading.Thread(target=_send).start()
