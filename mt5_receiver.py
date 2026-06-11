from app import limiter
import os
import sys
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timezone
import json
import traceback

# Ensure we can import app and models from current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from models import db, ChallengePurchase, AccountSnapshot, EATrade
    from rule_engine import process_sync
    HAS_APP_CONTEXT = True
except ImportError as e:
    print(f"⚠️ Could not import: {e}")
    HAS_APP_CONTEXT = False

receiver_bp = Blueprint(
    "receiver",
    __name__
)

# ========================================================================
# HELPER FUNCTIONS
# ========================================================================

def _safe_float(val, fallback=0.0):
    """Safely convert value to float"""
    if val is None:
        return fallback
    try:
        return float(val)
    except (ValueError, TypeError):
        return fallback

def _safe_int(val, fallback=0):
    """Safely convert value to int"""
    if val is None:
        return fallback
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return fallback

def parse_datetime(dt_str):
    """Parse datetime string to datetime object"""
    if not dt_str:
        return datetime.now(timezone.utc)
    if isinstance(dt_str, datetime):
        return dt_str.replace(tzinfo=timezone.utc) if dt_str.tzinfo is None else dt_str
    try:
        from dateutil import parser
        dt = parser.parse(str(dt_str))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return datetime.now(timezone.utc)

def clean_raw_data(raw_data):
    """Clean binary data, remove null bytes, convert to string"""
    try:
        if isinstance(raw_data, bytes):
            decoded = raw_data.decode('utf-8', errors='ignore')
            cleaned = decoded.replace('\x00', '')
            return json.loads(cleaned)
        elif isinstance(raw_data, dict):
            return raw_data
        else:
            return json.loads(str(raw_data))
    except Exception as e:
        print(f"⚠️ Clean error: {e}")
        return {}

# ========================================================================
# MT5 SYNC ENDPOINT
# ========================================================================

@receiver_bp.route("/api/mt5/sync", methods=["POST"])
@limiter.exempt
def mt5_sync():
    # Security checks
    if False and request.remote_addr not in ["13.48.130.215", "127.0.0.1", "172.31.38.116"]:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    
    if request.headers.get("X-Internal-Key") != "TGF_INT_xK92mQ27pL38nR4":
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    
    # Get raw data
    raw_data = request.get_data()
    print(f"🔥 RAW DATA (first 200 chars): {raw_data[:200]}")
    
    # Clean the data
    try:
        cleaned_str = raw_data.decode('utf-8', errors='ignore').strip('\x00')
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
                
                if journey.status not in ['active', 'funded']:
                    return jsonify({
                        "status": "ignored",
                        "message": f"Challenge status {journey.status} is not eligible for MT5 sync"
                    }), 200
                
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
                
                # ================================================================
                # STEP 1: Create AccountSnapshot + Save Open Trades FIRST
                # ================================================================
                
                snapshot = None
                if balance > 0 or equity > 0:
                    # DUPLICATE DETECTION: Check if this exact sync was just processed
                    last_snapshot = AccountSnapshot.query.filter_by(
                        challenge_purchase_id=journey.id
                    ).order_by(AccountSnapshot.timestamp.desc()).first()
                    
                    if last_snapshot:
                        time_diff = abs((datetime.now(timezone.utc) - last_snapshot.timestamp).total_seconds())
                        if (time_diff < 2 and 
                            abs(last_snapshot.balance - balance) < 0.01 and 
                            abs(last_snapshot.equity - equity) < 0.01):
                            print(f"[DUPLICATE] Sync skipped - same data within 2 seconds")
                            return jsonify({
                                "status": "duplicate",
                                "message": "Sync already processed"
                            }), 200
                    
                    # Create snapshot
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
                    db.session.flush()  # Get snapshot ID without committing
                
                # ================================================================
                # STEP 2: Save open trades to EATrade table
                # This ensures evidence system has current positions
                # ================================================================
                
                open_trades_data = data.get('open_trades', [])
                for td in open_trades_data:
                    ticket = td.get('ticket')
                    if not ticket:
                        continue
                    
                    try:
                        existing_trade = EATrade.query.filter_by(
                            challenge_purchase_id=journey.id,
                            ticket=ticket
                        ).first()
                        
                        if existing_trade:
                            # Update existing open trade
                            existing_trade.current_price = _safe_float(td.get('current_price'))
                            existing_trade.floating_pnl = _safe_float(td.get('floating_pnl'))
                            existing_trade.sl = _safe_float(td.get('sl'))
                            existing_trade.tp = _safe_float(td.get('tp'))
                            existing_trade.updated_at = datetime.now(timezone.utc)
                            
                            # If trade has close_time, mark as closed
                            if td.get('close_time'):
                                existing_trade.close_price = _safe_float(td.get('close_price'))
                                existing_trade.close_time = parse_datetime(td.get('close_time'))
                                existing_trade.profit = _safe_float(td.get('profit'))
                                existing_trade.status = 'closed'
                        else:
                            # Create new trade record
                            new_trade = EATrade(
                                challenge_purchase_id=journey.id,
                                ticket=ticket,
                                symbol=td.get('symbol', 'UNKNOWN'),
                                trade_type=int(td.get('type', 0)),
                                lots=_safe_float(td.get('lots')),
                                open_price=_safe_float(td.get('open_price')),
                                current_price=_safe_float(td.get('current_price')),
                                floating_pnl=_safe_float(td.get('floating_pnl')),
                                sl=_safe_float(td.get('sl')),
                                tp=_safe_float(td.get('tp')),
                                magic=_safe_int(td.get('magic')),
                                open_time=parse_datetime(td.get('open_time')),
                                close_time=parse_datetime(td.get('close_time')) if td.get('close_time') else None,
                                close_price=_safe_float(td.get('close_price')) if td.get('close_price') else None,
                                profit=_safe_float(td.get('profit')),
                                status='closed' if td.get('close_time') else 'open'
                            )
                            db.session.add(new_trade)
                    
                    except Exception as e:
                        print(f"[EATrade Save Error] ticket {ticket}: {e}")
                        continue
                
                # ================================================================
                # STEP 3: Mark closed trades in EATrade
                # ================================================================
                
                closed_trades_data = data.get('closed_trades', [])
                for td in closed_trades_data:
                    ticket = td.get('ticket')
                    if not ticket:
                        continue
                    
                    try:
                        existing_trade = EATrade.query.filter_by(
                            challenge_purchase_id=journey.id,
                            ticket=ticket
                        ).first()
                        
                        if existing_trade and existing_trade.status == 'open':
                            existing_trade.close_price = _safe_float(td.get('close_price'))
                            existing_trade.close_time = parse_datetime(td.get('close_time'))
                            existing_trade.profit = _safe_float(td.get('profit'))
                            existing_trade.floating_pnl = 0.0
                            existing_trade.status = 'closed'
                            existing_trade.updated_at = datetime.now(timezone.utc)
                        elif not existing_trade:
                            # Create the closed trade if it doesn't exist
                            new_trade = EATrade(
                                challenge_purchase_id=journey.id,
                                ticket=ticket,
                                symbol=td.get('symbol', 'UNKNOWN'),
                                trade_type=int(td.get('type', 0)),
                                lots=_safe_float(td.get('lots')),
                                open_price=_safe_float(td.get('open_price')),
                                close_price=_safe_float(td.get('close_price')),
                                current_price=_safe_float(td.get('close_price')),
                                profit=_safe_float(td.get('profit')),
                                floating_pnl=0.0,
                                sl=_safe_float(td.get('sl')),
                                tp=_safe_float(td.get('tp')),
                                magic=_safe_int(td.get('magic')),
                                open_time=parse_datetime(td.get('open_time')),
                                close_time=parse_datetime(td.get('close_time')),
                                status='closed'
                            )
                            db.session.add(new_trade)
                    
                    except Exception as e:
                        print(f"[EATrade Close Error] ticket {ticket}: {e}")
                        continue
                
                # ================================================================
                # STEP 4: Commit snapshot + trades BEFORE rule processing
                # This ensures evidence is preserved even if rule engine fails
                # ================================================================
                
                db.session.commit()
                print(f"[SNAPSHOT] Saved snapshot for challenge {journey.id} | Balance: {balance} | Equity: {equity}")
                
                # ================================================================
                # STEP 5: Run rule engine (separate transaction context)
                # If rule engine fails, snapshot is already saved
                # ================================================================
                
                try:
                    process_sync(journey, data)
                    db.session.commit()
                    print(f"[RULE ENGINE] Successfully processed challenge {journey.id}")
                except Exception as rule_error:
                    db.session.rollback()
                    print(f"[RULE ENGINE ERROR] Challenge {journey.id}: {rule_error}")
                    traceback.print_exc()
                    # Snapshot is already saved, continue to return response
                
                # ================================================================
                # STEP 6: Return response
                # ================================================================
                
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
            traceback.print_exc()
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        # Mock mode
        return jsonify({"status": "ok", "message": "Mock sync successful"}), 200