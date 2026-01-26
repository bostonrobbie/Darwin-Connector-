
import requests
import json
import sys
import os

# Config manually for the probe
API_KEY = "6/RTmjT2abFpvlWNbm0nVZeZ3Cr7YX89q3SV3J19hII="
BASE_URL = "https://api.topstepx.com"

endpoints = [
    "/api/User/profile",
    "/api/user/profile",
    "/api/User/Me",
    "/api/users/me",
    "/api/Account/list",
    "/api/accounts",
    "/api/account",
    "/api/Order/history",
    "/api/metadata/exchanges",
    "/api/market/status"
]

print(f"Probing {BASE_URL} with key ending in ...{API_KEY[-6:]}")
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

found = False
for ep in endpoints:
    url = f"{BASE_URL}{ep}"
    try:
        print(f"Checking {ep}...", end=" ")
        res = requests.get(url, headers=headers, timeout=5)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            print(f"!!! SUCCESS !!! Found valid endpoint: {ep}")
            print(f"Response: {res.text[:100]}...")
            found = True
            break
    except Exception as e:
        print(f"Error: {e}")

if not found:
    print("No valid endpoint found in list.")
