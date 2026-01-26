"""Test TopStep API connection and order placement"""
import requests
import json

# Credentials
USERNAME = "rgorham369@gmail.com"
API_KEY = "9lqnj/C6Uv7trbAT01n0QpU1Q1TSYgCcKp7n/WUw2Cc="
BASE_URL = "https://api.topstepx.com/api"

session = requests.Session()
token = None
account_id = None

def authenticate():
    """Get auth token"""
    global token
    print("[1] Authenticating...")
    resp = session.post(
        f"{BASE_URL}/Auth/loginKey",
        json={"userName": USERNAME, "apiKey": API_KEY},
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    if resp.status_code == 200:
        data = resp.json()
        token = data.get('token')
        print(f"    OK - Got token")
        return True
    print(f"    FAIL - {resp.status_code}: {resp.text}")
    return False

def get_accounts():
    """Get trading accounts"""
    global account_id
    print("[2] Getting accounts...")
    resp = session.post(
        f"{BASE_URL}/Account/search",
        json={"onlyActiveAccounts": True},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=10
    )
    if resp.status_code == 200:
        data = resp.json()
        accounts = data.get('accounts', [])
        for acc in accounts:
            print(f"    - {acc.get('name')}: ID={acc.get('id')}, Balance=${acc.get('balance'):,.2f}, CanTrade={acc.get('canTrade')}")
            if acc.get('canTrade') and not account_id:
                account_id = acc.get('id')
        if account_id:
            print(f"    Selected account ID: {account_id}")
            return True
    print(f"    FAIL - {resp.status_code}: {resp.text}")
    return False

def get_contracts():
    """Get available contracts"""
    print("[3] Getting available contracts...")

    resp = session.post(
        f"{BASE_URL}/Contract/search",
        json={"searchText": "MNQ", "live": False},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=10
    )
    print(f"    Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        contracts = data.get('contracts', [])
        print(f"    Found {len(contracts)} contracts")
        mnq_contract = None
        for c in contracts[:10]:
            name = c.get('name', '')
            cid = c.get('id')
            print(f"      - {name}: ID={cid}")
            if 'MNQ' in name.upper() and not mnq_contract:
                mnq_contract = c
        if mnq_contract:
            print(f"\n    MNQ Contract: {json.dumps(mnq_contract, indent=2)}")
            return mnq_contract.get('id')
    else:
        print(f"    Response: {resp.text[:500]}")
    return None

def test_order(contract_id):
    """Test order placement"""
    print(f"\n[4] Testing order with contractId={contract_id}...")

    # Try different order type values
    # type: 1 = Limit (failed), try 2 = Market?
    payloads = [
        # Try type=2 for Market
        {
            "accountId": account_id,
            "contractId": contract_id,
            "type": 2,  # Maybe Market = 2
            "side": 0,  # Buy = 0
            "size": 1
        },
        # Try type=0 for Market
        {
            "accountId": account_id,
            "contractId": contract_id,
            "type": 0,  # Maybe Market = 0
            "side": 0,
            "size": 1
        }
    ]

    for i, payload in enumerate(payloads):
        print(f"\n    Format {i+1}: {json.dumps(payload)}")
        resp = session.post(
            f"{BASE_URL}/Order/place",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            timeout=10
        )
        print(f"    Status: {resp.status_code}")
        result = resp.text[:500] if resp.text else 'Empty'
        print(f"    Response: {result}")

        # Parse and check
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get('success') == True:
                    print("    *** ORDER PLACED SUCCESSFULLY! ***")
                    return True
                else:
                    print(f"    Order sent but error: {data.get('errorMessage')}")
            except:
                pass

    return False

if __name__ == "__main__":
    print("=" * 60)
    print("TopStepX API Test")
    print("=" * 60)

    if authenticate():
        if get_accounts():
            contract_id = get_contracts()
            if contract_id:
                test_order(contract_id)
            else:
                print("\n    Could not find MNQ contract")
