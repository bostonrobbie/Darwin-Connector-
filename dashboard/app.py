import streamlit as st
import requests
import json
import time
import os
import pandas as pd

st.set_page_config(page_title="Unified Bridge", page_icon="📊", layout="wide")

# Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)

CONFIG = load_config()

IBKR_Url = f"http://127.0.0.1:{CONFIG['server']['ibkr_port']}"
MT5_Url = f"http://127.0.0.1:{CONFIG['server']['mt5_port']}"

def check_status(url):
    try:
        r = requests.get(f"{url}/health", timeout=2)
        if r.status_code == 200:
            return True, r.json()
    except:
        pass
    return False, {"status": "offline", "last_trade": "Unknown"}

# Custom CSS for cleaner look
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 10px 20px; }
    .block-container { padding-top: 2rem; }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; }
</style>
""", unsafe_allow_html=True)

# Header
st.title("📊 Unified Bridge")
st.caption("TradingView → MT5 + TopStep Trade Execution")

# Quick Status Bar
col1, col2, col3, col4 = st.columns(4)
mt5_online, mt5_data = check_status(MT5_Url)

# Get pause states from health endpoint
mt5_paused = mt5_data.get("mt5_paused", False) if mt5_online else False
ibkr_paused = mt5_data.get("ibkr_paused", False) if mt5_online else False
topstep_paused = mt5_data.get("topstep_paused", False) if mt5_online else False

with col1:
    if mt5_online and mt5_data.get("status") == "connected":
        if mt5_paused:
            st.warning("MT5: PAUSED")
        else:
            st.success("MT5: Connected")
    else:
        st.error("MT5: Offline")
with col2:
    ts_status = mt5_data.get("topstep_status", "unknown") if mt5_online else "offline"
    if ts_status == "connected":
        if topstep_paused:
            st.warning("TopStep: PAUSED")
        else:
            st.success("TopStep: Connected")
    else:
        st.warning("TopStep: " + ts_status.title())
with col3:
    st.metric("Last Trade", mt5_data.get("last_trade", "None")[:20] if mt5_data.get("last_trade") else "None")
with col4:
    if st.button("🚨 CLOSE ALL", type="primary"):
        try:
            requests.post(f"{MT5_Url}/close_all", json={
                "secret": CONFIG['security']['webhook_secret'],
                "platform": "all"
            }, timeout=5)
            st.toast("Close signal sent to all brokers!")
        except:
            st.error("Failed to send")

st.divider()

# Main Tabs
tab_webhook, tab_brokers, tab_controls, tab_trades, tab_settings = st.tabs(["📡 Webhook Setup", "🔗 Connections", "⏸️ Controls", "📊 Trade Log", "⚙️ Settings"])

# =====================
# TAB 1: WEBHOOK SETUP
# =====================
with tab_webhook:
    # Get subdomain for use throughout
    mt5_subdomain = CONFIG.get('tunnels', {}).get('mt5_subdomain', 'major-cups-pick')
    persistent_url = f"https://{mt5_subdomain}.loca.lt/webhook"

    # Quick Copy Section at Top
    st.subheader("Quick Setup (Copy & Paste)")

    copy_col1, copy_col2 = st.columns(2)
    with copy_col1:
        st.markdown("**Webhook URL:**")
        st.code(persistent_url, language="text")
    with copy_col2:
        st.markdown("**Alert Message:**")
        alert_json = f'{{"secret":"{CONFIG["security"]["webhook_secret"]}","action":"{{{{strategy.order.action}}}}","symbol":"{{{{ticker}}}}","volume":{{{{strategy.order.contracts}}}}}}'
        st.code(alert_json, language="json")

    st.divider()
    st.subheader("Detailed Configuration")

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("### 1. Webhook URL")
        st.success("✓ Ready to use - Copy this URL to TradingView")

        st.code(persistent_url, language="text")
        st.caption("This URL is persistent and never changes")

        st.markdown("### 2. Alert Message")
        st.success("✓ Ready to use - Copy this JSON to TradingView")

        # Pre-configured webhook template
        webhook_template = f'''{{
    "secret": "{CONFIG['security']['webhook_secret']}",
    "action": "{{{{strategy.order.action}}}}",
    "symbol": "{{{{ticker}}}}",
    "volume": {{{{strategy.order.contracts}}}}
}}'''

        st.code(webhook_template, language="json")

        st.markdown("### 3. Quick Copy Templates")

        # Manual templates
        col_buy, col_sell, col_close = st.columns(3)
        with col_buy:
            st.markdown("**Manual BUY:**")
            buy_template = f'{{"secret":"{CONFIG["security"]["webhook_secret"]}","action":"BUY","symbol":"MNQ1!","volume":1}}'
            st.code(buy_template, language="json")
        with col_sell:
            st.markdown("**Manual SELL:**")
            sell_template = f'{{"secret":"{CONFIG["security"]["webhook_secret"]}","action":"SELL","symbol":"MNQ1!","volume":1}}'
            st.code(sell_template, language="json")
        with col_close:
            st.markdown("**Manual CLOSE:**")
            close_template = f'{{"secret":"{CONFIG["security"]["webhook_secret"]}","action":"CLOSE","symbol":"MNQ1!","volume":0}}'
            st.code(close_template, language="json")

    with col_right:
        st.markdown("### How It Works")
        st.markdown(f"""
        ```
        TradingView Alert
              ↓
        {mt5_subdomain}.loca.lt
              ↓
        Unified Bridge (Your PC)
              ↓
        ┌─────────────────────────────┐
        │                             │
        ↓                             ↓
        MT5 (Darwinex)           TopStep
        1 Mini = 1 Mini          1 Mini = 5 Micros
        Direct passthrough       Max 15 Micros (3 Minis)
        LIMIT Orders             LIMIT Orders
        ```
        """)

        st.markdown("### Contract Conversion")
        st.markdown("""
        | Alert Volume | MT5 | TopStep |
        |-------------|-----|---------|
        | 1 Mini | 1 Mini | 5 MNQ Micros |
        | 2 Minis | 2 Minis | 10 MNQ Micros |
        | 3 Minis | 3 Minis | 15 MNQ Micros (MAX) |
        | 4+ Minis | 4+ Minis | 15 MNQ Micros (capped) |
        """)

        st.markdown("### Supported Actions")
        st.markdown("""
        - `BUY` - Open long position
        - `SELL` - Open short position
        - `CLOSE` / `EXIT` / `FLATTEN` - Close all positions
        """)

        st.markdown("### Test Your Setup")
        col_test1, col_test2 = st.columns(2)
        with col_test1:
            if st.button("📤 Send Test BUY", use_container_width=True):
                try:
                    r = requests.post(f"{MT5_Url}/webhook", json={
                        "secret": CONFIG['security']['webhook_secret'],
                        "action": "BUY",
                        "symbol": "MNQ1!",
                        "volume": 1
                    }, timeout=5)
                    st.success("Test BUY sent!")
                except Exception as e:
                    st.error(f"Failed: {e}")
        with col_test2:
            if st.button("📤 Send Test CLOSE", use_container_width=True):
                try:
                    r = requests.post(f"{MT5_Url}/webhook", json={
                        "secret": CONFIG['security']['webhook_secret'],
                        "action": "CLOSE",
                        "symbol": "MNQ1!",
                        "volume": 0
                    }, timeout=5)
                    st.success("Test CLOSE sent!")
                except Exception as e:
                    st.error(f"Failed: {e}")


# =====================
# TAB 2: CONNECTIONS
# =====================
with tab_brokers:
    st.subheader("Broker Connections")

    broker_config = load_config()

    col_mt5, col_topstep = st.columns(2)

    # --- MT5 ---
    with col_mt5:
        st.markdown("### MetaTrader 5")

        # Status indicator
        if mt5_online and mt5_data.get("status") == "connected":
            st.success("✓ Connected to " + broker_config.get('mt5', {}).get('server', 'Unknown'))
        else:
            st.error("✗ Disconnected")

        with st.expander("Connection Settings", expanded=False):
            mt5_conf = broker_config.get('mt5', {})

            mt5_login = st.text_input("Account #", value=str(mt5_conf.get('login', '')), key="mt5_login")
            mt5_password = st.text_input("Password", value=mt5_conf.get('password', ''), type="password", key="mt5_pass")
            mt5_server = st.text_input("Server", value=mt5_conf.get('server', ''), key="mt5_server")
            mt5_path = st.text_input("Terminal Path", value=mt5_conf.get('path', ''), key="mt5_path")

            if st.button("💾 Save MT5", key="save_mt5", use_container_width=True):
                broker_config['mt5']['login'] = int(mt5_login) if mt5_login.isdigit() else 0
                broker_config['mt5']['password'] = mt5_password
                broker_config['mt5']['server'] = mt5_server
                broker_config['mt5']['path'] = mt5_path
                save_config(broker_config)
                st.success("Saved! Restart to apply.")

        st.markdown("**Routing:** Direct passthrough (1:1)")
        st.caption("1 Mini alert = 1 Mini on MT5")

    # --- TOPSTEP ---
    with col_topstep:
        st.markdown("### TopStep")

        ts_conf = broker_config.get('topstep', {})
        ts_enabled = ts_conf.get('enabled', False)

        # Status indicator
        if ts_enabled:
            if ts_status == "connected":
                st.success("✓ Connected (Eval Mode)" if ts_conf.get('eval_mode') else "✓ Connected (Funded)")
            else:
                st.warning("⚠ Enabled but not connected")
        else:
            st.info("○ Disabled")

        with st.expander("Connection Settings", expanded=False):
            ts_enable = st.checkbox("Enable TopStep", value=ts_enabled, key="ts_enable")

            if ts_enable:
                ts_username = st.text_input("Username (ProjectX)", value=ts_conf.get('username', ''), key="ts_user")
                ts_api_key = st.text_input("API Key", value=ts_conf.get('api_key', ''), type="password", key="ts_api")
                st.caption("Get API key from ProjectX Dashboard → Settings → API")
                ts_mock = st.checkbox("Mock Mode (no real trades)", value=ts_conf.get('mock_mode', False), key="ts_mock")
                ts_eval = st.checkbox("Eval Mode", value=ts_conf.get('eval_mode', True), key="ts_eval")

                if st.button("💾 Save TopStep", key="save_ts", use_container_width=True):
                    broker_config['topstep']['enabled'] = ts_enable
                    broker_config['topstep']['username'] = ts_username
                    broker_config['topstep']['api_key'] = ts_api_key
                    broker_config['topstep']['mock_mode'] = ts_mock
                    broker_config['topstep']['eval_mode'] = ts_eval
                    save_config(broker_config)
                    st.success("Saved! Restart to apply.")
            else:
                if st.button("💾 Save (Disabled)", key="save_ts_off", use_container_width=True):
                    broker_config['topstep']['enabled'] = False
                    save_config(broker_config)
                    st.success("TopStep disabled.")

        st.markdown("**Routing:** Mini → Micro conversion")
        st.caption("1 Mini = 5 MNQ Micros (max 15)")

    st.divider()

    # IBKR Section (collapsed)
    with st.expander("Interactive Brokers (Coming Soon)", expanded=False):
        st.info("IBKR integration will be configured later.")
        st.caption("Currently forwarding is disabled.")


# =====================
# TAB 3: BROKER CONTROLS (Pause Buttons)
# =====================
with tab_controls:
    st.subheader("Broker Controls")
    st.caption("Pause or resume trading on individual brokers without stopping the system")

    control_col1, control_col2, control_col3 = st.columns(3)

    # Helper function to toggle pause
    def toggle_pause(broker, current_state):
        try:
            new_state = not current_state
            r = requests.post(f"{MT5_Url}/pause/{broker}", json={"paused": new_state}, timeout=5)
            if r.status_code == 200:
                return True
        except:
            pass
        return False

    with control_col1:
        st.markdown("### MT5 (Darwinex)")
        if mt5_online and mt5_data.get("status") == "connected":
            st.success("Status: Connected")
        else:
            st.error("Status: Disconnected")

        if mt5_paused:
            st.error("🔴 PAUSED - Trades blocked")
            if st.button("▶️ Resume MT5", key="resume_mt5", use_container_width=True):
                if toggle_pause("mt5", True):
                    st.success("MT5 Resumed!")
                    st.rerun()
        else:
            st.success("🟢 ACTIVE - Trading enabled")
            if st.button("⏸️ Pause MT5", key="pause_mt5", use_container_width=True, type="primary"):
                if toggle_pause("mt5", False):
                    st.warning("MT5 Paused!")
                    st.rerun()

    with control_col2:
        st.markdown("### TopStep")
        if mt5_data.get("topstep_status") == "connected":
            st.success("Status: Connected")
        else:
            st.warning("Status: Disconnected")

        if topstep_paused:
            st.error("🔴 PAUSED - Trades blocked")
            if st.button("▶️ Resume TopStep", key="resume_ts", use_container_width=True):
                if toggle_pause("topstep", True):
                    st.success("TopStep Resumed!")
                    st.rerun()
        else:
            st.success("🟢 ACTIVE - Trading enabled")
            if st.button("⏸️ Pause TopStep", key="pause_ts", use_container_width=True, type="primary"):
                if toggle_pause("topstep", False):
                    st.warning("TopStep Paused!")
                    st.rerun()

    with control_col3:
        st.markdown("### IBKR")
        st.info("Status: Coming Soon")

        if ibkr_paused:
            st.error("🔴 PAUSED - Trades blocked")
            if st.button("▶️ Resume IBKR", key="resume_ibkr", use_container_width=True):
                if toggle_pause("ibkr", True):
                    st.success("IBKR Resumed!")
                    st.rerun()
        else:
            st.success("🟢 ACTIVE - Trading enabled")
            if st.button("⏸️ Pause IBKR", key="pause_ibkr", use_container_width=True, type="primary"):
                if toggle_pause("ibkr", False):
                    st.warning("IBKR Paused!")
                    st.rerun()

    st.divider()

    # Hard Exit Settings
    st.markdown("### Hard Exit Settings")
    st.caption("Automatically close all positions at end of trading day")

    trading_hours = load_config().get('trading_hours', {})

    he_col1, he_col2 = st.columns(2)
    with he_col1:
        hard_exit_enabled = st.checkbox(
            "Enable Hard Exit",
            value=trading_hours.get('hard_exit_enabled', True),
            key="hard_exit_enabled"
        )
        hard_exit_time = st.text_input(
            "Exit Time (24h format)",
            value=trading_hours.get('hard_exit_time', '16:50'),
            key="hard_exit_time",
            help="Time in HH:MM format (New York timezone)"
        )

    with he_col2:
        st.info(f"Current setting: Close all positions at **{trading_hours.get('hard_exit_time', '16:50')} ET** Mon-Fri")
        if st.button("💾 Save Hard Exit Settings", use_container_width=True):
            cfg = load_config()
            if 'trading_hours' not in cfg:
                cfg['trading_hours'] = {}
            cfg['trading_hours']['hard_exit_enabled'] = hard_exit_enabled
            cfg['trading_hours']['hard_exit_time'] = hard_exit_time
            save_config(cfg)
            st.success("Settings saved! Restart to apply.")


# =====================
# TAB 4: TRADE LOG
# =====================
with tab_trades:
    st.subheader("Trade Log")
    st.caption("View and verify all executed trades")

    # Filters
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        platform_filter = st.selectbox("Platform", ["All", "MT5", "TopStep", "IBKR", "REJECTED"], key="platform_filter")
    with filter_col2:
        limit_filter = st.selectbox("Show Last", [25, 50, 100, 500], key="limit_filter")
    with filter_col3:
        if st.button("🔄 Refresh", key="refresh_trades"):
            st.rerun()

    # Fetch trades
    try:
        params = {"limit": limit_filter}
        if platform_filter != "All":
            params["platform"] = platform_filter

        r = requests.get(f"{MT5_Url}/trades", params=params, timeout=5)
        if r.status_code == 200:
            trade_data = r.json()
            trades = trade_data.get('trades', [])

            if trades:
                # Summary metrics
                metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
                successful = sum(1 for t in trades if t.get('status') == 'success')
                failed = sum(1 for t in trades if t.get('status') not in ['success', 'paused'])
                paused = sum(1 for t in trades if t.get('status') == 'paused')
                avg_latency = sum(t.get('latency_ms', 0) for t in trades) / len(trades) if trades else 0

                with metric_col1:
                    st.metric("Total Trades", len(trades))
                with metric_col2:
                    st.metric("Successful", successful)
                with metric_col3:
                    st.metric("Failed/Rejected", failed)
                with metric_col4:
                    st.metric("Avg Latency", f"{avg_latency:.0f}ms")

                st.divider()

                # Trade table
                import pandas as pd
                df = pd.DataFrame(trades)

                # Select columns to display
                display_cols = ['timestamp', 'platform', 'symbol', 'action', 'volume', 'status',
                               'expected_price', 'executed_price', 'slippage', 'latency_ms']
                available_cols = [c for c in display_cols if c in df.columns]

                if available_cols:
                    st.dataframe(df[available_cols], use_container_width=True, height=400)

                # Export button
                st.divider()
                export_col1, export_col2 = st.columns([1, 3])
                with export_col1:
                    if st.button("📥 Export to CSV", key="export_csv"):
                        try:
                            csv_data = df.to_csv(index=False)
                            st.download_button(
                                label="Download CSV",
                                data=csv_data,
                                file_name=f"trades_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                        except Exception as e:
                            st.error(f"Export failed: {e}")

                # Detailed view expander
                with st.expander("View Trade Details"):
                    if trades:
                        trade_id = st.selectbox("Select Trade", range(len(trades)),
                                               format_func=lambda i: f"{trades[i].get('timestamp', 'N/A')} - {trades[i].get('action', 'N/A')} {trades[i].get('symbol', 'N/A')}")
                        if trade_id is not None:
                            st.json(trades[trade_id])
            else:
                st.info("No trades found.")
        else:
            st.error(f"Failed to fetch trades: {r.status_code}")
    except Exception as e:
        st.error(f"Could not load trades: {e}")
        st.info("Make sure the MT5 Bridge is running.")


# =====================
# TAB 5: SETTINGS
# =====================
with tab_settings:
    st.subheader("System Settings")

    settings_config = load_config()

    col_exec, col_system = st.columns(2)

    with col_exec:
        st.markdown("### Execution")

        exec_conf = settings_config.get('mt5', {}).get('execution', {})

        order_type = st.selectbox(
            "Order Type",
            ["LIMIT", "MARKET"],
            index=0 if exec_conf.get('default_type', 'LIMIT') == 'LIMIT' else 1,
            key="order_type"
        )

        slippage = st.number_input(
            "Slippage Offset (ticks)",
            min_value=0, max_value=20, value=exec_conf.get('slippage_offset_ticks', 2),
            key="slippage",
            help="For LIMIT orders: offset from current price"
        )

        st.markdown("### TopStep Conversion")
        st.caption("How many micros per 1 mini alert")

        micros_per_mini = st.number_input(
            "Micros per Mini",
            min_value=1, max_value=10, value=settings_config.get('topstep', {}).get('micros_per_mini', 5),
            key="micros_per_mini"
        )

        max_micros = st.number_input(
            "Max Micros (cap)",
            min_value=1, max_value=50, value=settings_config.get('topstep', {}).get('max_micros', 15),
            key="max_micros"
        )

        st.caption(f"Example: 2 Minis = {min(2 * micros_per_mini, max_micros)} Micros")

        if st.button("💾 Save Execution Settings", use_container_width=True):
            settings_config['mt5']['execution']['default_type'] = order_type
            settings_config['mt5']['execution']['slippage_offset_ticks'] = slippage
            settings_config['topstep']['micros_per_mini'] = micros_per_mini
            settings_config['topstep']['max_micros'] = max_micros
            save_config(settings_config)
            st.success("Settings saved!")

    with col_system:
        st.markdown("### Webhook Security")

        st.text_input("Secret Key", value=settings_config['security']['webhook_secret'], disabled=True)

        if st.button("🔄 Generate New Secret"):
            import uuid
            new_secret = str(uuid.uuid4())
            settings_config['security']['webhook_secret'] = new_secret
            save_config(settings_config)
            st.success("New secret generated! Update TradingView alerts.")
            st.rerun()

        st.markdown("### Server Ports")
        st.caption("Requires restart to apply changes")

        mt5_port = st.number_input("MT5 Bridge Port", value=settings_config['server']['mt5_port'], key="mt5_port_set")

        if st.button("💾 Save Ports", use_container_width=True):
            settings_config['server']['mt5_port'] = int(mt5_port)
            save_config(settings_config)
            st.success("Ports saved! Restart required.")

        st.markdown("### Quick Actions")

        col_a1, col_a2 = st.columns(2)
        with col_a1:
            if st.button("🌐 Open TopStep", use_container_width=True):
                import webbrowser
                webbrowser.open("https://topstepx.com/trade")
        with col_a2:
            if st.button("📂 Open Logs", use_container_width=True):
                log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
                os.startfile(log_dir)

    st.divider()

    # Logs section
    with st.expander("Recent Logs"):
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'mt5.log')
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                lines = f.readlines()[-15:]
                for line in lines:
                    st.text(line.strip()[:100])
        else:
            st.info("No logs yet.")


# Footer
st.divider()
st.caption("Unified Bridge v2.0 | MT5 + TopStep")

# Auto-refresh every 5 seconds
time.sleep(5)
st.rerun()
