import MetaTrader5 as mt5
import requests
import time
from datetime import datetime

# =====================================================================
# CONFIG — edit these
# =====================================================================
MT5_LOGIN    = 101776700
MT5_PASSWORD = "Kunal_8805"
MT5_SERVER   = "XMGlobal-MT5 5"

CHALLENGE_TOKEN = "41626f4fc1179307bbded16717579526521f0bbd0ac9ee2babf02f129430b0ab"
CHALLENGE_ID    = 454890
SERVER_URL      = "http://127.0.0.1:5000/api/mt5/sync"
SEND_INTERVAL   = 10  # seconds

# =====================================================================
# INIT
# =====================================================================
print("Initializing MT5...")
if not mt5.initialize():
    print(f"❌ MT5 initialize failed: {mt5.last_error()}")
    quit()
print("✅ MT5 initialized")

print(f"Logging in as {MT5_LOGIN} on {MT5_SERVER}...")
if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
    print(f"❌ MT5 login failed: {mt5.last_error()}")
    quit()
print("✅ MT5 logged in successfully")

# =====================================================================
# MAIN LOOP
# =====================================================================
while True:
    try:
        # --- Account ---
        account = mt5.account_info()
        if account is None:
            print(f"❌ account_info() returned None: {mt5.last_error()}")
            time.sleep(SEND_INTERVAL)
            continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # --- Open positions ---
        open_trades = []
        positions = mt5.positions_get()
        if positions:
            for p in positions:
                open_trades.append({
                    "ticket":        p.ticket,
                    "symbol":        p.symbol,
                    "type":          p.type,       # 0=BUY, 1=SELL
                    "lots":          round(p.volume, 2),
                    "open_price":    p.price_open,
                    "current_price": p.price_current,
                    "floating_pnl":  round(p.profit, 2),
                    "sl":            p.sl,
                    "tp":            p.tp,
                    "open_time":     datetime.fromtimestamp(p.time).strftime("%Y-%m-%d %H:%M:%S")
                })

        # --- Closed trades (last 2) ---
        closed_trades = []
        from datetime import timedelta
        from_date = datetime.now() - timedelta(days=7)
        history = mt5.history_deals_get(from_date, datetime.now())
        if history:
            closing_deals = [
                d for d in history
                if d.entry in (1, 3)  # DEAL_ENTRY_OUT=1, DEAL_ENTRY_INOUT=3
                and d.type in (0, 1)  # DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1
            ]
            # Sort newest first, take last 2
            closing_deals = sorted(closing_deals, key=lambda d: d.time, reverse=True)[:2]
            for d in closing_deals:
                closed_trades.append({
                    "ticket":      d.ticket,
                    "symbol":      d.symbol,
                    "type":        d.type,
                    "lots":        round(d.volume, 2),
                    "close_price": d.price,
                    "profit":      round(d.profit, 2),
                    "close_time":  datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
                })

        # --- Build payload ---
        payload = {
            "challenge_token": CHALLENGE_TOKEN,
            "challenge_id":    CHALLENGE_ID,
            "ea_version":      "1.0.0-py",
            "terminal_build":  0,
            "heartbeat":       now,
            "account": {
                "account_login":  account.login,
                "broker_server":  account.server,
                "balance":        round(account.balance, 2),
                "equity":         round(account.equity, 2),
                "free_margin":    round(account.margin_free, 2),
                "margin_used":    round(account.margin, 2),
                "leverage":       account.leverage,
                "currency":       account.currency,
                "terminal_time":  now
            },
            "open_trades":   open_trades,
            "closed_trades": closed_trades
        }

        print(f"[{now}] Balance: {account.balance} | Equity: {account.equity} | Sending...")

        # --- Send ---
        response = requests.post(SERVER_URL, json=payload, timeout=5)
        print(f"✅ Server response: {response.status_code} | {response.text[:100]}")

    except Exception as e:
        print(f"❌ Error: {e}")

    time.sleep(SEND_INTERVAL)