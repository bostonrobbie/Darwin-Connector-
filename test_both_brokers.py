"""
Test both MT5 and TopStep order execution directly
"""
import json
import time

print("=" * 60)
print("UNIFIED BRIDGE - BROKER TEST")
print("=" * 60)

# Load config
with open('config.json', 'r') as f:
    CONFIG = json.load(f)

# ============================================
# TEST 1: TOPSTEP
# ============================================
print("\n[1] TESTING TOPSTEP...")
print("-" * 40)

import requests

USERNAME = CONFIG['topstep']['username']
API_KEY = CONFIG['topstep']['api_key']
BASE_URL = CONFIG['topstep']['base_url']

session = requests.Session()

# Authenticate
print("    Authenticating...")
resp = session.post(
    f"{BASE_URL}/Auth/loginKey",
    json={"userName": USERNAME, "apiKey": API_KEY},
    headers={"Content-Type": "application/json"},
    timeout=10
)

if resp.status_code != 200:
    print(f"    FAIL: Auth failed - {resp.status_code}")
else:
    token = resp.json().get('token')
    print(f"    OK: Got token")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Get account
    print("    Getting accounts...")
    resp = session.post(
        f"{BASE_URL}/Account/search",
        json={"onlyActiveAccounts": True},
        headers=headers,
        timeout=10
    )

    if resp.status_code == 200:
        accounts = resp.json().get('accounts', [])
        account_id = None
        for acc in accounts:
            if acc.get('canTrade'):
                account_id = acc.get('id')
                print(f"    OK: Using account {acc.get('name')} (${acc.get('balance'):,.2f})")
                break

        if account_id:
            # Get MNQ contract
            print("    Getting MNQ contract...")
            resp = session.post(
                f"{BASE_URL}/Contract/search",
                json={"searchText": "MNQ", "live": False},
                headers=headers,
                timeout=10
            )

            if resp.status_code == 200:
                contracts = resp.json().get('contracts', [])
                contract_id = None
                for c in contracts:
                    if c.get('activeContract'):
                        contract_id = c.get('id')
                        print(f"    OK: Found contract {c.get('name')} -> {contract_id}")
                        break

                if contract_id:
                    # Place test BUY order (1 MNQ)
                    print("\n    PLACING TEST BUY ORDER (1 MNQ)...")
                    payload = {
                        "accountId": account_id,
                        "contractId": contract_id,
                        "type": 2,  # Market
                        "side": 0,  # Buy
                        "size": 1
                    }
                    print(f"    Payload: {json.dumps(payload)}")

                    resp = session.post(
                        f"{BASE_URL}/Order/place",
                        json=payload,
                        headers=headers,
                        timeout=10
                    )

                    print(f"    Status: {resp.status_code}")
                    result = resp.json() if resp.text else {}
                    print(f"    Response: {json.dumps(result, indent=2)}")

                    if result.get('success'):
                        print(f"\n    *** TOPSTEP BUY ORDER SUCCESS! Order ID: {result.get('orderId')} ***")

                        # Wait a moment then close
                        print("\n    Waiting 2 seconds...")
                        time.sleep(2)

                        # Place test SELL to close
                        print("    PLACING TEST SELL ORDER (1 MNQ) to close...")
                        payload['side'] = 1  # Sell
                        resp = session.post(
                            f"{BASE_URL}/Order/place",
                            json=payload,
                            headers=headers,
                            timeout=10
                        )
                        result = resp.json() if resp.text else {}
                        if result.get('success'):
                            print(f"    *** TOPSTEP SELL ORDER SUCCESS! Order ID: {result.get('orderId')} ***")
                        else:
                            print(f"    Sell result: {result}")
                    else:
                        print(f"    FAIL: {result.get('errorMessage')}")

# ============================================
# TEST 2: MT5
# ============================================
print("\n" + "=" * 60)
print("[2] TESTING MT5...")
print("-" * 40)

try:
    import MetaTrader5 as mt5

    MT5_CONF = CONFIG['mt5']

    print("    Initializing MT5...")
    if not mt5.initialize(path=MT5_CONF['path']):
        print(f"    FAIL: Init failed - {mt5.last_error()}")
    else:
        print("    OK: MT5 initialized")

        print("    Logging in...")
        if not mt5.login(
            login=int(MT5_CONF['login']),
            password=MT5_CONF['password'],
            server=MT5_CONF['server']
        ):
            print(f"    FAIL: Login failed - {mt5.last_error()}")
        else:
            print(f"    OK: Logged in to {MT5_CONF['server']}")

            # Check account
            account = mt5.account_info()
            if account:
                print(f"    Account: {account.login}, Balance: ${account.balance:,.2f}")

            # Get symbol info
            symbol = "NQ_H"  # Mapped symbol for MNQ1!
            print(f"\n    Getting symbol info for {symbol}...")
            info = mt5.symbol_info(symbol)
            if info:
                print(f"    OK: {symbol} - min_lot={info.volume_min}, max_lot={info.volume_max}")

                # Get tick
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    print(f"    Current price: Bid={tick.bid}, Ask={tick.ask}")

                    # Try to place a BUY order (1.0 lot = 1 mini)
                    print(f"\n    PLACING TEST BUY ORDER (1.0 lot {symbol})...")

                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": 1.0,
                        "type": mt5.ORDER_TYPE_BUY,
                        "price": tick.ask,
                        "magic": MT5_CONF.get('magic_number', 0),
                        "comment": "Test-Order",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }

                    print(f"    Request: vol={request['volume']}, price={request['price']}")

                    result = mt5.order_send(request)
                    if result is None:
                        print(f"    FAIL: order_send returned None - {mt5.last_error()}")
                    else:
                        print(f"    Result: retcode={result.retcode}, comment={result.comment}")

                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"\n    *** MT5 BUY ORDER SUCCESS! Order: {result.order} ***")

                            # Wait then close
                            print("\n    Waiting 2 seconds...")
                            time.sleep(2)

                            # Close position
                            print("    CLOSING POSITION...")
                            positions = mt5.positions_get(symbol=symbol)
                            if positions:
                                for pos in positions:
                                    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                                    close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

                                    close_req = {
                                        "action": mt5.TRADE_ACTION_DEAL,
                                        "symbol": pos.symbol,
                                        "volume": pos.volume,
                                        "type": close_type,
                                        "position": pos.ticket,
                                        "price": close_price,
                                        "magic": MT5_CONF.get('magic_number', 0),
                                        "comment": "Test-Close",
                                        "type_time": mt5.ORDER_TIME_GTC,
                                        "type_filling": mt5.ORDER_FILLING_IOC,
                                    }

                                    close_result = mt5.order_send(close_req)
                                    if close_result and close_result.retcode == mt5.TRADE_RETCODE_DONE:
                                        print(f"    *** MT5 CLOSE SUCCESS! ***")
                                    else:
                                        print(f"    Close result: {close_result.comment if close_result else 'None'}")
                        else:
                            print(f"    FAIL: {result.comment}")
            else:
                print(f"    FAIL: Could not get symbol info for {symbol}")
                print(f"    Available symbols containing 'NQ':")
                symbols = mt5.symbols_get()
                for s in symbols:
                    if 'NQ' in s.name.upper():
                        print(f"      - {s.name}")

        mt5.shutdown()

except ImportError:
    print("    FAIL: MetaTrader5 module not installed")
except Exception as e:
    print(f"    FAIL: Exception - {e}")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
