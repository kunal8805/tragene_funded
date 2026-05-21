# test_heartbeat.py
import requests
from datetime import datetime

CHALLENGE_TOKEN = "41626f4fc1179307bbded16717579526521f0bbd0ac9ee2babf02f129430b0ab"

print("Sending heartbeat to MT5 Receiver...")

try:
    response = requests.post(
        "http://localhost:5000/api/mt5/sync",
        json={
            "challenge_token": CHALLENGE_TOKEN,
            "balance": 52500,
            "equity": 52300,
            "broker_time": datetime.now().isoformat(),
            "trades": []
        },
        timeout=10
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except requests.exceptions.ConnectionError:
    print("ERROR: Cannot connect to port 5000. Is mt5_receiver.py running?")
except Exception as e:
    print(f"ERROR: {e}")
