from app import limiter
import os
import sys
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timezone
import json

# Ensure we can import app and models from current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from models import db, ChallengePurchase, AccountSnapshot
    from rule_engine import process_sync
    HAS_APP_CONTEXT = True
except ImportError as e:
    print(f"⚠️ Could not import: {e}")
    HAS_APP_CONTEXT = False

receiver_bp = Blueprint(
    "receiver",
    __name__
)

def clean_raw_data(raw_data):
    """Clean binary data, remove null bytes, convert to string"""
    try:
        # Decode bytes to string, ignore errors
        if isinstance(raw_data, bytes):
            decoded = raw_data.decode('utf-8', errors='ignore')
            # Remove null characters
            cleaned = decoded.replace('\x00', '')
            # Try to parse as JSON
            return json.loads(cleaned)
        elif isinstance(raw_data, dict):
            return raw_data
        else:
            return json.loads(str(raw_data))
    except Exception as e:
        print(f"⚠️ Clean error: {e}")
        return {}

@receiver_bp.route("/api/mt5/sync", methods=["POST"])
@limiter.exempt
def mt5_sync():
    # ADD THESE TWO CHECKS
    if False and request.remote_addr not in ["13.48.130.215", "127.0.0.1", "172.31.38.116"]:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    
    if request.headers.get("X-Internal-Key") != "TGF_INT_xK92mQ27pL38nR4":
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    
    # Get raw data
    raw_data = request.get_data()
    print(f"🔥 RAW DATA (first 200 chars): {raw_data[:200]}")
    
    # Clean the data
    try:
        # Try to parse JSON from raw bytes
        cleaned_str = raw_data.decode('utf-8', errors='ignore').strip('\x00')
        # Find JSON part (between { and })
        start = cleaned_str.find('{')
        end = cleaned_str.rfind('}') + 1
        if start != -1 and end > start:
            cleaned_str = cleaned_str[start:end]
        
        data = json.loads(cleaned_str)
        print(f"🔥 CLEANED JSON: {data}")
    except Exception as e:
        print(f"❌ JSON parse error: {e}")
        return jsonify({"status": "error", "message": "Invalid JSON format"}), 400
    
    # Extract token
    token = data.get('challenge_token') or data.get('token') or request.headers.get('Authorization')
    if token and token.startswith('Bearer '):
        token = token[7:]
        
    if not token:
        return jsonify({"status": "error", "message": "Challenge token is required"}), 400
        
    if HAS_APP_CONTEXT:
        try:
            with current_app.app_context():
                journey = ChallengePurchase.query.filter_by(challenge_token=token).first()
                if not journey:
                    return jsonify({"status": "error", "message": "Invalid challenge token"}), 401
                
                # Check if challenge is terminated
                if journey.is_terminated:
                    return jsonify({"status": "error", "message": "Challenge has been breached/terminated"}), 403
                
                # Check if challenge is already failed
                if journey.status in ['failed', 'expired', 'revoked']:
                    return jsonify({"status": "error", "message": f"Challenge already {journey.status}"}), 403
                
                # Get account data
                account_data = data.get('account', {})
                balance = float(account_data.get('balance', data.get('balance', journey.current_balance or 0)))
                equity = float(account_data.get('equity', data.get('equity', journey.current_equity or 0)))
                
                # Update heartbeat
                journey.last_heartbeat = datetime.now(timezone.utc)
                journey.ea_connected = True
                
                # Update balance and equity
                if balance > 0:
                    journey.current_balance = balance
                    journey.account_balance = balance
                if equity > 0:
                    journey.current_equity = equity
                    journey.equity = equity
                
                # Get trades
                trades = data.get('closed_trades', []) + data.get('open_trades', [])
                
                # Format data for rule engine
                engine_data = {
                    'balance': balance,
                    'equity': equity,
                    'broker_time': account_data.get('terminal_time') or data.get('heartbeat'),
                    'trades': trades
                }
                
                # Create snapshot
                if balance > 0 or equity > 0:
                    snapshot = AccountSnapshot(
                        challenge_purchase_id=journey.id,
                        timestamp=datetime.now(timezone.utc),
                        ea_version=data.get('ea_version', '1.0'),
                        terminal_build=int(data.get('terminal_build', 0)),
                        mt5_login=str(account_data.get('account_login', '')),
                        broker_server=account_data.get('broker_server', ''),
                        balance=balance,
                        equity=equity,
                        free_margin=float(account_data.get('free_margin', 0.0)),
                        margin_used=float(account_data.get('margin_used', 0.0))
                    )
                    db.session.add(snapshot)
                
                # Call rule engine
                process_sync(journey, data)
                
                db.session.commit()
                
                return jsonify({
                    "status": "ok",
                    "message": "Sync successful",
                    "challenge": {
                        "id": journey.id,
                        "type": journey.challenge_type,
                        "phase": journey.current_phase,
                        "status": journey.status,
                        "monitoring_status": journey.monitoring_status
                    },
                    "metrics": {
                        "profit_percent": journey.profit_percent,
                        "daily_drawdown": journey.daily_drawdown,
                        "overall_drawdown": journey.overall_drawdown,
                        "trading_days": journey.trading_days,
                        "risk_score": journey.risk_score
                    }
                }), 200
                
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        # Mock mode
        return jsonify({"status": "ok", "message": "Mock sync successful"}), 200