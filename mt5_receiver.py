import os
import sys
from flask import Flask, request, jsonify
from datetime import datetime, timezone

# Ensure we can import app and models from current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app import app, db
    from models import TradingJourney, AccountSnapshot
    HAS_APP_CONTEXT = True
except ImportError as e:
    print(f"⚠️ Could not import main app or models: {e}. Running in standalone mockup mode.")
    HAS_APP_CONTEXT = False

receiver_app = Flask(__name__)

@receiver_app.route("/api/mt5/sync", methods=["POST"])
def mt5_sync():
    data = request.get_json(silent=True) or {}
    print("🔥 RAW DATA:", request.data)
    print("🔥 JSON:", data)
    
    token = data.get('challenge_token') or data.get('token') or request.headers.get('Authorization')
    if token and token.startswith('Bearer '):
        token = token[7:]
        
    if not token:
        return jsonify({"status": "error", "message": "Challenge token is required"}), 400
        
    if HAS_APP_CONTEXT:
        try:
            with app.app_context():
                journey = TradingJourney.query.filter_by(challenge_token=token).first()
                if not journey:
                    return jsonify({"status": "error", "message": "Invalid challenge token"}), 401
                    
                if journey.is_terminated:
                    return jsonify({"status": "error", "message": "Challenge has been breached/terminated"}), 403
                    
                # Update heartbeat
                journey.last_heartbeat = datetime.now(timezone.utc)
                journey.ea_connected = True
                
                # Update balance and equity if provided
                if 'balance' in data:
                    journey.current_balance = float(data['balance'])
                    journey.account_balance = float(data['balance'])
                if 'equity' in data:
                    journey.current_equity = float(data['equity'])
                    journey.equity = float(data['equity'])
                    
                # Create snapshot if financial details are provided
                if 'balance' in data and 'equity' in data:
                    snapshot = AccountSnapshot(
                        challenge_purchase_id=journey.id,
                        timestamp=datetime.now(timezone.utc),
                        ea_version=data.get('ea_version', '1.0'),
                        terminal_build=int(data.get('terminal_build', 0)),
                        mt5_login=journey.mt5_login or str(data.get('mt5_login', '')),
                        broker_server=data.get('broker_server', ''),
                        balance=float(data['balance']),
                        equity=float(data['equity']),
                        free_margin=float(data.get('free_margin', 0.0)),
                        margin_used=float(data.get('margin_used', 0.0))
                    )
                    db.session.add(snapshot)
                    
                db.session.commit()
                return jsonify({
                    "status": "ok",
                    "message": "Sync successful",
                    "challenge": {
                        "id": journey.id,
                        "type": journey.challenge_type,
                        "phase": journey.current_phase,
                        "status": journey.status
                    }
                }), 200
        except Exception as e:
            print(f"❌ Error syncing with database: {e}")
            return jsonify({"status": "error", "message": "Database sync failed"}), 500
    else:
        # Mock mode
        if token == "breached_token":
            return jsonify({"status": "error", "message": "Challenge is terminated/breached"}), 403
        return jsonify({"status": "ok", "message": "Mock sync successful"}), 200

if __name__ == "__main__":
    port = int(os.getenv("MT5_PORT", 5000))
    receiver_app.run(host="0.0.0.0", port=port, debug=True)