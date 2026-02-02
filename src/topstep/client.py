import requests
import json
import logging
import time
from colorama import Fore, Style
from src.utils.logger import LogManager

# Logger specific to TopStep
logger = LogManager.get_logger("TopStep", log_file="logs/topstep.log")

# TopStepX API Enums
ORDER_TYPE_LIMIT = 1
ORDER_TYPE_MARKET = 2
ORDER_TYPE_STOP = 3
ORDER_TYPE_STOP_LIMIT = 4

SIDE_BUY = 0
SIDE_SELL = 1


class TopStepClient:
    def __init__(self, config):
        self.config = config.get('topstep', {})
        self.enabled = self.config.get('enabled', False)
        self.mock_mode = self.config.get('mock_mode', True)
        self.username = self.config.get('username', '')
        self.api_key = self.config.get('api_key', '')
        self.base_url = self.config.get('base_url', 'https://api.topstepx.com/api').rstrip('/')
        self.symbol_map = self.config.get('symbol_map', {})
        self.max_retries = self.config.get('max_retries', 3)

        self.consecutive_failures = 0
        self.circuit_open = False
        self.connected = False
        self.session = requests.Session()
        self.access_token = None
        self.account_id = self.config.get('account_id')  # Use configured account if set
        self.account_name = None

        # Contract ID cache (symbol -> contractId)
        self.contract_cache = {}

        # Keep-Alive
        import threading
        self.running = True
        self.ka_thread = threading.Thread(target=self._keep_alive_loop, daemon=True)
        self.ka_thread.start()

    def _keep_alive_loop(self):
        """Periodically refreshes token to keep session alive."""
        if not self.enabled or self.mock_mode:
            return
        while self.running:
            time.sleep(300)  # Refresh every 5 minutes
            try:
                if self.connected:
                    self._authenticate()
            except:
                pass

    def _authenticate(self):
        """Authenticate with TopStepX API to get access token."""
        if not self.api_key:
            logger.error(f"{Fore.RED}TopStepX: No API key configured{Style.RESET_ALL}")
            return False

        if not self.username:
            logger.error(f"{Fore.RED}TopStepX: No username configured{Style.RESET_ALL}")
            return False

        try:
            auth_url = f"{self.base_url}/Auth/loginKey"

            payload = {
                "userName": self.username,
                "apiKey": self.api_key
            }

            headers = {
                "Content-Type": "application/json"
            }

            response = self.session.post(auth_url, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('token')
                if self.access_token:
                    logger.info(f"{Fore.GREEN}TopStepX: Authenticated successfully as {self.username}{Style.RESET_ALL}")
                    self._get_accounts()
                    return True
                else:
                    logger.error(f"{Fore.RED}TopStepX: No token in response{Style.RESET_ALL}")
                    return False
            else:
                logger.error(f"{Fore.RED}TopStepX: Auth failed - {response.status_code}: {response.text}{Style.RESET_ALL}")
                return False

        except Exception as e:
            logger.error(f"{Fore.RED}TopStepX: Auth exception: {e}{Style.RESET_ALL}")
            return False

    def _get_accounts(self):
        """Get available trading accounts using search endpoint."""
        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            response = self.session.post(
                f"{self.base_url}/Account/search",
                json={"onlyActiveAccounts": False},  # Include all accounts to find configured ID
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                accounts = data.get('accounts', [])
                if accounts:
                    # If account_id is pre-configured, find that specific account
                    configured_id = self.account_id
                    logger.info(f"DEBUG: Configured account_id from config: {configured_id} (type: {type(configured_id).__name__})")
                    logger.info(f"DEBUG: All accounts from API: {[(a.get('id'), a.get('name'), a.get('canTrade')) for a in accounts]}")
                    if configured_id:
                        for acc in accounts:
                            acc_id = acc.get('id')
                            logger.info(f"DEBUG: Comparing {acc_id} (type: {type(acc_id).__name__}) == {configured_id}")
                            if acc_id == configured_id:
                                self.account_name = acc.get('name')
                                balance = acc.get('balance', 0)
                                logger.info(f"{Fore.GREEN}TopStepX: Using configured account {self.account_name} (ID: {self.account_id}, Balance: ${balance:,.2f}){Style.RESET_ALL}")
                                return
                        logger.warning(f"{Fore.YELLOW}TopStepX: Configured account {configured_id} not found, using first tradeable{Style.RESET_ALL}")

                    # Fall back to first tradeable account
                    for acc in accounts:
                        if acc.get('canTrade', False):
                            self.account_id = acc.get('id')
                            self.account_name = acc.get('name')
                            balance = acc.get('balance', 0)
                            logger.info(f"{Fore.GREEN}TopStepX: Using account {self.account_name} (ID: {self.account_id}, Balance: ${balance:,.2f}){Style.RESET_ALL}")
                            return
                    self.account_id = accounts[0].get('id')
                    self.account_name = accounts[0].get('name')
                    logger.warning(f"{Fore.YELLOW}TopStepX: Using account {self.account_name} (may not be tradeable){Style.RESET_ALL}")
                else:
                    logger.warning(f"{Fore.YELLOW}TopStepX: No accounts found{Style.RESET_ALL}")
            else:
                logger.warning(f"TopStepX: Account search returned {response.status_code}")
        except Exception as e:
            logger.warning(f"TopStepX: Could not fetch accounts: {e}")

    def _get_contract_id(self, symbol):
        """Get the full contract ID for a symbol (e.g., MNQ -> CON.F.US.MNQ.H26)"""
        # Check cache first
        if symbol in self.contract_cache:
            return self.contract_cache[symbol]

        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            response = self.session.post(
                f"{self.base_url}/Contract/search",
                json={"searchText": symbol, "live": False},  # live=False for sim/eval accounts
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                contracts = data.get('contracts', [])
                for c in contracts:
                    if c.get('activeContract', False):
                        contract_id = c.get('id')
                        self.contract_cache[symbol] = contract_id
                        logger.info(f"TopStepX: Resolved {symbol} -> {contract_id}")
                        return contract_id
            logger.warning(f"TopStepX: Could not find contract for {symbol}")
        except Exception as e:
            logger.warning(f"TopStepX: Contract search error: {e}")

        return None

    def validate_connection(self):
        """Checks connection to API on startup."""
        if not self.enabled:
            logger.info("TopStepX module is disabled.")
            return False

        if self.mock_mode:
            logger.info(f"{Fore.YELLOW}TopStepX running in MOCK MODE. No real connection check.{Style.RESET_ALL}")
            self.connected = True
            return True

        logger.info(f"Validating TopStepX Connection to {self.base_url}...")

        if self._authenticate():
            self.connected = True
            return True
        else:
            logger.error(f"{Fore.RED}TopStepX: Authentication failed{Style.RESET_ALL}")
            return False

    def execute_trade(self, data):
        """
        Executes a trade order.
        Data expected: {"symbol": "MNQ", "action": "BUY", "volume": 5.0}
        Actions: BUY, SELL, CLOSE/EXIT/FLATTEN
        """
        if not self.enabled:
            return {"status": "skipped", "message": "Disabled"}

        if self.circuit_open:
            logger.error(f"{Fore.RED}Circuit Breaker OPEN. Skipping TopStepX order.{Style.RESET_ALL}")
            return {"status": "error", "message": "Circuit Breaker Open"}

        symbol = data.get('symbol')
        action = data.get('action', '').upper()
        volume = float(data.get('volume', 0))

        # Handle CLOSE/EXIT/FLATTEN actions
        if action in ['CLOSE', 'EXIT', 'FLATTEN']:
            if self.mock_mode:
                msg = f"MOCK CLOSE: {symbol} -> TopStepX (Success)"
                logger.info(f"{Fore.MAGENTA}{msg}{Style.RESET_ALL}")
                return {"status": "success", "mode": "mock", "message": msg}
            return self._close_position(symbol)

        if volume <= 0:
            return {"status": "error", "message": "Invalid Volume"}

        if self.mock_mode:
            msg = f"MOCK ORDER: {action} {int(volume)} {symbol} -> TopStepX (Success)"
            logger.info(f"{Fore.MAGENTA}{msg}{Style.RESET_ALL}")
            return {"status": "success", "mode": "mock", "message": msg}

        if not self.access_token:
            if not self._authenticate():
                return {"status": "error", "message": "Authentication failed"}

        return self._send_order(symbol, action, int(volume))

    def _close_position(self, symbol):
        """Close position for a symbol on TopStep using Position/closeContract."""
        if not self.access_token:
            if not self._authenticate():
                return {"status": "error", "message": "Authentication failed"}

        # Get contract ID
        contract_id = self._get_contract_id(symbol)
        if not contract_id:
            return {"status": "error", "message": f"Could not find contract for {symbol}"}

        url = f"{self.base_url}/Position/closeContract"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "accountId": self.account_id,
            "contractId": contract_id
        }

        try:
            logger.info(f"TopStepX Close Position: {json.dumps(payload)}")
            response = self.session.post(url, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                result = response.json() if response.text else {}
                if result.get('success', False):
                    self.consecutive_failures = 0
                    logger.info(f"{Fore.GREEN}TopStepX Position Closed: {symbol}{Style.RESET_ALL}")
                    return {"status": "success", "data": result}
                else:
                    error_msg = result.get('errorMessage', 'Unknown error')
                    logger.warning(f"TopStepX Close response: {error_msg}")
                    return {"status": "success", "data": result}  # May be no position to close
            elif response.status_code == 401:
                logger.warning("TopStepX: Token expired, re-authenticating...")
                if self._authenticate():
                    return self._close_position(symbol)
                self._handle_failure(f"HTTP 401: Re-auth failed")
                return {"status": "error", "code": 401, "message": "Authentication failed"}
            else:
                self._handle_failure(f"HTTP {response.status_code}: {response.text}")
                return {"status": "error", "code": response.status_code, "body": response.text}

        except Exception as e:
            self._handle_failure(str(e))
            return {"status": "error", "message": str(e)}

    def _send_order(self, symbol, action, quantity):
        """Send a market order to TopStepX."""
        # Get contract ID
        contract_id = self._get_contract_id(symbol)
        if not contract_id:
            return {"status": "error", "message": f"Could not find contract for {symbol}"}

        url = f"{self.base_url}/Order/place"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        # TopStepX order format (confirmed working)
        payload = {
            "accountId": self.account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_MARKET,  # 2 = Market
            "side": SIDE_BUY if action == "BUY" else SIDE_SELL,  # 0 = Buy, 1 = Sell
            "size": quantity
        }

        try:
            logger.info(f"TopStepX Order: {json.dumps(payload)}")
            response = self.session.post(url, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                result = response.json() if response.text else {}
                if result.get('success', False):
                    self.consecutive_failures = 0
                    order_id = result.get('orderId')
                    logger.info(f"{Fore.GREEN}TopStepX Order Placed: {action} {quantity} {symbol} (Order ID: {order_id}){Style.RESET_ALL}")
                    return {"status": "success", "data": result}
                else:
                    error_msg = result.get('errorMessage', 'Unknown error')
                    self._handle_failure(f"Order rejected: {error_msg}")
                    return {"status": "error", "message": error_msg, "data": result}
            elif response.status_code == 401:
                logger.warning("TopStepX: Token expired, re-authenticating...")
                if self._authenticate():
                    return self._send_order(symbol, action, quantity)
                self._handle_failure(f"HTTP 401: Re-auth failed")
                return {"status": "error", "code": 401, "message": "Authentication failed"}
            else:
                self._handle_failure(f"HTTP {response.status_code}: {response.text}")
                logger.error(f"TopStep Error: {response.text}")
                return {"status": "error", "code": response.status_code, "body": response.text}

        except Exception as e:
            self._handle_failure(str(e))
            return {"status": "error", "message": str(e)}

    def _handle_failure(self, error_msg):
        self.consecutive_failures += 1
        logger.error(f"{Fore.RED}TopStepX Failure ({self.consecutive_failures}/{self.max_retries}): {error_msg}{Style.RESET_ALL}")

        if self.consecutive_failures >= self.max_retries:
            self.circuit_open = True
            logger.critical(f"{Fore.RED}TopStepX CIRCUIT BREAKER TRIPPED. Stopping requests.{Style.RESET_ALL}")
