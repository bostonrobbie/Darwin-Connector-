# Interactive Brokers (IBKR) Bridge

This bridge connects TradingView to **Trader Workstation (TWS)** or **IB Gateway**.

## 1. Prerequisites
1.  **Install TWS**: Download "Trader Workstation" from Interactive Brokers.
2.  **Enable API in TWS**:
    *   Open TWS -> File -> Global Configuration.
    *   Go to **API** -> **Settings**.
    *   **Check**: "Enable ActiveX and Socket Clients".
    *   **Uncheck**: "Read-Only API".
    *   **Port**: 
        *   **7497** = Paper Trading (Demo)
        *   **7496** = Live Trading (Real Money)
    *   **NOTE**: You must update `src/config/settings.json` if you switch!

## 2. Installation
Run inside this folder:
```bash
pip install -r requirements.txt
```

## 3. Usage
Double-click **`start_ibkr.bat`**.

## 4. Configuration
*   **Symbol format**: IBKR uses detailed contracts.
    *   Forex: `EURUSD` (Defaults to "CASH", "IDEALPRO").
    *   Stock: `AAPL` (Must set `sec_type` to "STK" in JSON payload).

## 5. Webhook Payload Example
Set your TradingView Webhook to your Tunnel URL + `/webhook`.

```json
{
    "secret": "fd70ac19-6154-4354-a8ba-b345b511ed93",
    "action": "BUY",
    "symbol": "EURUSD",
    "volume": 20000, 
    "secType": "CASH",
    "currency": "USD",
    "exchange": "IDEALPRO"
}
```
*Note: `volume` for FX in IBKR is literal units (e.g. 20000), NOT lots.*
