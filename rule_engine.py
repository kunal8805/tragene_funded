"""
TRAGENE FUNDED - RULE ENGINE v3.0
Production-Grade Violation Detection System

ALL FEATURES:
- Equity-based violation detection (works on OPEN trades)
- Immutable violation evidence package
- Violations persist even after equity recovery
- Admin review workflow (UNDER_REVIEW → Admin decides)
- Lowest equity tracking (lifetime + phase + daily)
- No missed violations (MULTIPLE violations now captured)
- 🛡️ Mandatory Stop-Loss Rule
- ⏱️ Trading Activity Rule (No 4+ Day Gaps)
- ⚖️ Maximum Lot Size Rule (NEW)
- ✅ FIXED: Violations detected even when already under review
"""

from datetime import datetime, timezone, date, timedelta
from collections import defaultdict
from models import (
    db, TradingJourney, RuleLog, TradeHistory, RuleViolation,
    ViolationEvidence, EATrade, Notification, UserNotification
)
import traceback
import json

# ========================================================================
# CONSTANTS
# ========================================================================

class ChallengeState:
    ACTIVE       = 'active'
    OFFLINE      = 'offline'
    UNDER_REVIEW = 'under_review'
    FLAGGED      = 'flagged'
    FAILED       = 'failed'
    PASSED       = 'passed'
    FUNDED       = 'funded'
    PHASE1_ACTIVE = 'phase1_active'
    PHASE2_ACTIVE = 'phase2_active'
    FUNDED_ACTIVE = 'funded_active'

class Severity:
    INFO      = 'info'
    WARNING   = 'warning'
    VIOLATION = 'violation'
    CRITICAL  = 'critical'
    SUCCESS   = 'success'

RISK_WEIGHTS = {
    'balance_manipulation': 50,
    'credit_detected':      40,
    'ea_disconnection':     20,
    'weekend_trading':      30,
    'leverage_abuse':       25,
    'account_reset':        50,
    'multiple_accounts':    40,
    'hedging_detected':     20,
    'martingale_pattern':   25,
    'equity_spike':         35,
    'copy_trading':         45,
    'sl_missing':           50,
    'activity_gap':         35,
    'daily_drawdown':       45,
    'overall_drawdown':     45,
    'lot_size_violation':   30,  # ⚖️ NEW
}

BALANCE_MANIPULATION_THRESHOLD = 10.0
MARTINGALE_LOT_MULTIPLIER = 2.0
HEDGE_DUST_THRESHOLD = 0.01

# ========================================================================
# SAFE TYPE HELPERS
# ========================================================================

def _safe_float(val, fallback=0.0):
    if val is None or val == '' or val == 'None':
        return fallback
    try:
        return float(val)
    except (ValueError, TypeError):
        return fallback

def _safe_int(val, fallback=0):
    if val is None or val == '' or val == 'None':
        return fallback
    try:
        s = str(val).strip()
        if ":" in s:
            s = s.split(":")[-1]
        return int(float(s))
    except (ValueError, TypeError):
        return fallback

def _parse_leverage(val):
    s = str(val or '0').strip()
    try:
        if ':' in s:
            return int(s.split(':')[-1])
        return int(float(s)) if s else 0
    except (ValueError, TypeError):
        return 0

def _dd_label(value):
    return 'Static Balance Based' if value == 'static' else 'Equity Based'

def _daily_drawdown_values(challenge, model):
    if model == 'static':
        start = _safe_float(challenge.day_start_balance) or _safe_float(challenge.daily_start_balance)
        lowest = _safe_float(challenge.phase_lowest_balance_today) or _safe_float(challenge.current_balance)
        current = _safe_float(challenge.current_balance)
    else:
        start = _safe_float(challenge.day_start_equity)
        lowest = _safe_float(challenge.lowest_equity_today)
        current = _safe_float(challenge.current_equity)
    pct = max(0.0, (start - lowest) / start * 100) if start > 0 and lowest > 0 else 0.0
    return pct, start, lowest, current

def _overall_drawdown_values(challenge, model, account_size):
    current = _safe_float(challenge.current_balance if model == 'static' else challenge.current_equity)
    pct = max(0.0, (account_size - current) / account_size * 100) if account_size > 0 else 0.0
    return pct, account_size, current, current

def ensure_utc(dt):
    if not dt:
        return None
    try:
        if isinstance(dt, str):
            dt = parse_datetime(dt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

def notify_user(user_id, title, message):
    try:
        notification = Notification(
            title=title,
            message=message,
            is_global=False,
            target_user_id=user_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db.session.add(notification)
        db.session.flush()
        db.session.add(UserNotification(notification_id=notification.id, user_id=user_id))
    except Exception as e:
        print(f"[NOTIFY ERROR] {e}")

# ========================================================================
# MAIN ENTRY POINT
# ========================================================================

def process_sync(challenge, data):
    """
    Called from receiver.py after every heartbeat.
    CRITICAL: Violations are detected and recorded IMMEDIATELY.
    """
    try:
        print(f"\n[RULE ENGINE] ── Challenge {challenge.id} ─────────────────────")

        if challenge.status not in (
            ChallengeState.ACTIVE,
            ChallengeState.FUNDED,
            ChallengeState.PHASE1_ACTIVE,
            ChallengeState.PHASE2_ACTIVE,
            ChallengeState.FUNDED_ACTIVE,
            ChallengeState.UNDER_REVIEW
        ):
            print(f"[IGNORED] Challenge status {challenge.status}")
            return

        # 1. Auto-initialise on first sync
        _ensure_starting_balance(challenge, data)

        # 2. Persist trade history
        save_trade_history(challenge, data)

        # 3. Recalculate all metrics (including lowest equity tracking)
        update_metrics(challenge, data)

        # 4. Load rule set for current phase
        rules = get_active_rules(challenge)

        # 5. CORE: Configurable drawdown violation detection
        check_equity_violations(challenge, data, rules)

        # 🛡️ 5.5: Check Stop-Loss mandatory rule
        check_stoploss_mandatory(challenge, data, rules)

        # ⏱️ 5.6: Check trading activity rule
        check_trading_activity(challenge, data, rules)

        # ⚖️ 5.7: Check lot size compliance (NEW)
        check_lot_size_compliance(challenge, data, rules)

        # 6. Core challenge rules (profit target, expiry)
        check_rules(challenge, data, rules)

        # 7. Anti-cheat suite
        check_anti_cheat(challenge, data)

        # 8. Finalise status / progress
        update_challenge_status(challenge, rules)

        print(
            f"[RULE ENGINE] Done │ Profit: {challenge.profit_percent:.2f}% │ "
            f"DD(daily): {challenge.daily_drawdown:.2f}% │ "
            f"DD(overall): {challenge.overall_drawdown:.2f}% │ "
            f"Lowest Eq Life: ${challenge.lowest_equity_lifetime:.2f} │ "
            f"Risk: {challenge.risk_score} │ Status: {challenge.status}"
        )

        return True

    except Exception as e:
        print("\n" + "="*80)
        print("[RULE ENGINE INTERNAL ERROR]")
        print(f"Challenge ID: {challenge.id}")
        print(f"Error: {str(e)}")
        traceback.print_exc()
        print("="*80)
        db.session.rollback()
        return False

# ========================================================================
# 🛡️ MANDATORY STOP-LOSS RULE
# ========================================================================

def check_stoploss_mandatory(challenge, data, rules):
    """
    MANDATORY STOP-LOSS RULE
    Every trade must have a PHYSICAL stop-loss set within grace period.
    No mental stop-losses allowed. HARD BREACH on violation.
    """
    if not rules.get('sl_mandatory_enabled'):
        return

    if challenge.status in (ChallengeState.PASSED, ChallengeState.FAILED):
        return
    
    if challenge.is_terminated:
        return

    grace_minutes = rules.get('sl_grace_period_minutes', 3)

    open_trades = data.get('open_trades', [])
    db_open_trades = EATrade.query.filter_by(
        challenge_purchase_id=challenge.id,
        status='open'
    ).all()

    now_utc = datetime.now(timezone.utc)
    violations_found = []

    for trade in open_trades:
        ticket = trade.get('ticket')
        sl = _safe_float(trade.get('sl'))
        open_time_str = trade.get('open_time')

        if not open_time_str:
            continue

        open_time = parse_datetime(open_time_str)
        minutes_open = (now_utc - open_time).total_seconds() / 60

        if sl <= 0 and minutes_open > grace_minutes:
            violations_found.append({
                'ticket': ticket,
                'symbol': trade.get('symbol', 'UNKNOWN'),
                'open_time': open_time_str,
                'minutes_open': round(minutes_open, 1),
                'sl': sl
            })

    for trade in db_open_trades:
        if trade.sl <= 0 and trade.open_time:
            minutes_open = (now_utc - trade.open_time).total_seconds() / 60
            if minutes_open > grace_minutes:
                if not any(v['ticket'] == trade.ticket for v in violations_found):
                    violations_found.append({
                        'ticket': trade.ticket,
                        'symbol': trade.symbol,
                        'open_time': trade.open_time.isoformat() if trade.open_time else None,
                        'minutes_open': round(minutes_open, 1),
                        'sl': trade.sl
                    })

    if violations_found:
        existing = ViolationEvidence.query.filter_by(
            challenge_purchase_id=challenge.id,
            violation_type='sl_missing',
            is_reviewed=False
        ).first()
        
        if existing:
            print(f"[SL SKIP] Unreviewed SL violation already exists #{existing.id}")
            return

        trade_list = ', '.join([f"#{v['ticket']} ({v['symbol']})" for v in violations_found])
        reason = (
            f"Mandatory Stop-Loss Violation!\n"
            f"Trade(s) without SL: {trade_list}\n"
            f"Grace Period: {grace_minutes} minutes\n"
            f"Each trade open for > {grace_minutes} min without physical stop-loss.\n"
            f"Consequence: HARD BREACH - Account frozen, no payout."
        )

        print(f"[VIOLATION DETECTED] Stop-Loss Missing: {trade_list}")

        create_violation_evidence(
            challenge=challenge, data=data,
            violation_type='sl_missing', rule_name='Mandatory Stop-Loss',
            rule_limit=grace_minutes,
            actual_value=max(v['minutes_open'] for v in violations_found),
            reason=reason, severity='hard_breach'
        )

        challenge.violation_reason = f"Mandatory Stop-Loss violation: {len(violations_found)} trade(s) without SL"
        challenge.status = ChallengeState.UNDER_REVIEW
        challenge.monitoring_status = ChallengeState.UNDER_REVIEW
        challenge.review_required = True
        challenge.violation_reviewed = False
        challenge.sl_violation_count = (challenge.sl_violation_count or 0) + 1
        challenge.risk_score = min(100, (challenge.risk_score or 0) + RISK_WEIGHTS.get('sl_missing', 50))

        log_rule(challenge.id, "mandatory_stoploss", Severity.VIOLATION,
                 f"Stop-Loss missing on {len(violations_found)} trade(s): {trade_list}",
                 max(v['minutes_open'] for v in violations_found), grace_minutes)

        notify_user(challenge.user_id, "Account Under Compliance Review",
                    "Your account is currently under compliance review. You will be notified once the review is complete.")

        db.session.commit()


# ========================================================================
# ⏱️ TRADING ACTIVITY RULE (NO 4+ DAY GAPS)
# ========================================================================

def check_trading_activity(challenge, data, rules):
    """
    TRADING ACTIVITY RULE
    Trader must place at least 1 trade every 3-4 days.
    No 4+ day gaps allowed. HARD BREACH on violation.
    """
    if not rules.get('activity_rule_enabled'):
        return

    if challenge.status in (ChallengeState.PASSED, ChallengeState.FAILED):
        return
    
    if challenge.is_terminated:
        return

    max_inactive = rules.get('max_inactive_days', 4)

    last_trade = challenge.last_trade_date
    if not last_trade:
        if challenge.start_date:
            last_trade = challenge.start_date.date() if hasattr(challenge.start_date, 'date') else challenge.start_date
        else:
            return

    now_date = datetime.now(timezone.utc).date()
    days_since_last_trade = (now_date - last_trade).days

    if days_since_last_trade >= max_inactive:
        existing = ViolationEvidence.query.filter_by(
            challenge_purchase_id=challenge.id,
            violation_type='activity_gap',
            is_reviewed=False
        ).first()
        
        if existing:
            print(f"[ACTIVITY SKIP] Unreviewed activity violation already exists #{existing.id}")
            return

        reason = (
            f"Trading Activity Violation!\n"
            f"Last trade date: {last_trade}\n"
            f"Days inactive: {days_since_last_trade} days\n"
            f"Maximum allowed: {max_inactive} days\n"
            f"Consequence: HARD BREACH - Account frozen, no payout."
        )

        print(f"[VIOLATION DETECTED] Trading Activity Gap: {days_since_last_trade} days")

        create_violation_evidence(
            challenge=challenge, data=data,
            violation_type='activity_gap', rule_name='Trading Activity',
            rule_limit=max_inactive, actual_value=days_since_last_trade,
            reason=reason, severity='hard_breach'
        )

        challenge.violation_reason = f"Trading activity violation: {days_since_last_trade} days inactive (max: {max_inactive})"
        challenge.status = ChallengeState.UNDER_REVIEW
        challenge.monitoring_status = ChallengeState.UNDER_REVIEW
        challenge.review_required = True
        challenge.violation_reviewed = False
        challenge.activity_violation_count = (challenge.activity_violation_count or 0) + 1
        challenge.risk_score = min(100, (challenge.risk_score or 0) + RISK_WEIGHTS.get('activity_gap', 35))

        log_rule(challenge.id, "trading_activity", Severity.VIOLATION,
                 f"Trading gap: {days_since_last_trade} days (max: {max_inactive})",
                 days_since_last_trade, max_inactive)

        notify_user(challenge.user_id, "Account Under Compliance Review",
                    "Your account is currently under compliance review. You will be notified once the review is complete.")

        db.session.commit()


# ========================================================================
# ⚖️ MAX LOT SIZE RULE (NEW)
# ========================================================================

def check_lot_size_compliance(challenge, data, rules):
    """
    MAX LOT SIZE RULE
    Trader cannot open positions larger than the allowed lot size.
    Violation action: Flag for review OR Hard Breach (configurable).
    """
    if not rules.get('max_lot_size_enabled'):
        return

    if challenge.status in (ChallengeState.PASSED, ChallengeState.FAILED):
        return
    
    if challenge.is_terminated:
        return

    max_lot = rules.get('max_lot_size', 0.02)
    action = rules.get('lot_size_violation_action', 'flag')

    open_trades = data.get('open_trades', [])
    violations_found = []

    for trade in open_trades:
        lots = _safe_float(trade.get('lots'))
        if lots > max_lot:
            violations_found.append({
                'ticket': trade.get('ticket'),
                'symbol': trade.get('symbol', 'UNKNOWN'),
                'lots': lots,
                'max_allowed': max_lot
            })

    if violations_found:
        existing = ViolationEvidence.query.filter_by(
            challenge_purchase_id=challenge.id,
            violation_type='lot_size_violation',
            is_reviewed=False
        ).first()
        
        if existing:
            print(f"[LOT SIZE SKIP] Unreviewed lot size violation already exists #{existing.id}")
            return

        trade_list = ', '.join([f"#{v['ticket']} ({v['symbol']} - {v['lots']} lots)" for v in violations_found])
        is_hard = (action == 'hard_breach')
        reason = (
            f"Maximum Lot Size Violation!\n"
            f"Trade(s) exceeding max lot size ({max_lot}): {trade_list}\n"
            f"Max Allowed: {max_lot} lots\n"
            f"Consequence: {'HARD BREACH - Account frozen, no payout.' if is_hard else 'Account flagged for admin review.'}"
        )

        print(f"[VIOLATION DETECTED] Lot Size Exceeded: {trade_list}")

        create_violation_evidence(
            challenge=challenge, data=data,
            violation_type='lot_size_violation', rule_name='Maximum Lot Size',
            rule_limit=max_lot, actual_value=max(v['lots'] for v in violations_found),
            reason=reason, severity='hard_breach' if is_hard else 'warning'
        )

        challenge.violation_reason = f"Lot size violation: {len(violations_found)} trade(s) exceed {max_lot} lots max"
        challenge.status = ChallengeState.UNDER_REVIEW
        challenge.monitoring_status = ChallengeState.UNDER_REVIEW
        challenge.review_required = True
        challenge.violation_reviewed = False
        challenge.lot_size_violation_count = (challenge.lot_size_violation_count or 0) + 1
        challenge.risk_score = min(100, (challenge.risk_score or 0) + RISK_WEIGHTS.get('lot_size_violation', 30))

        log_rule(challenge.id, "max_lot_size", Severity.VIOLATION,
                 f"Lot size violation: {len(violations_found)} trade(s) exceed {max_lot} lots",
                 max(v['lots'] for v in violations_found), max_lot)

        notify_user(challenge.user_id, "Account Under Compliance Review",
                    "Your account is currently under compliance review. You will be notified once the review is complete.")

        db.session.commit()


# ========================================================================
# EQUITY-BASED VIOLATION DETECTION
# ========================================================================

def check_equity_violations(challenge, data, rules):
    """
    Check configured drawdown violations and record immutable evidence.
    Continues monitoring even if already under review.
    Only skips for TERMINATED challenges (FAILED/PASSED).
    """
    if challenge.status in (ChallengeState.PASSED, ChallengeState.FAILED):
        return
    
    if challenge.is_terminated:
        return

    daily_limit = _safe_float(rules.get('daily_loss'))
    overall_limit = _safe_float(rules.get('overall_loss'))
    daily_model = rules.get('daily_dd_type', 'equity')
    overall_model = rules.get('overall_dd_type', 'equity')

    account_size = _safe_float(
        challenge.challenge_template.account_size
    ) if challenge.challenge_template else _safe_float(challenge.starting_balance)

    # CHECK DAILY DRAWDOWN
    if daily_limit > 0:
        daily_dd_pct, start_value, lowest_value, current_value = _daily_drawdown_values(challenge, daily_model)

        if start_value > 0 and lowest_value > 0 and daily_dd_pct >= daily_limit:
            existing = ViolationEvidence.query.filter_by(
                challenge_purchase_id=challenge.id,
                violation_type='daily_drawdown',
                is_reviewed=False
            ).first()
            
            if not existing:
                value_name = 'Balance' if daily_model == 'static' else 'Equity'
                reason = (
                    f"Daily Drawdown Breached!\n"
                    f"Drawdown Model = {_dd_label(daily_model)}\n"
                    f"Daily Limit = {daily_limit}%\n"
                    f"Actual Drawdown = {daily_dd_pct:.2f}%\n"
                    f"Day Start {value_name}: ${start_value:.2f}\n"
                    f"Lowest {value_name} Today: ${lowest_value:.2f}\n"
                    f"Current {value_name}: ${current_value:.2f}"
                )

                print(f"[VIOLATION DETECTED] Daily DD: {daily_dd_pct:.2f}% >= {daily_limit}%")

                create_violation_evidence(
                    challenge=challenge, data=data,
                    violation_type='daily_drawdown', rule_name='Daily Drawdown',
                    rule_limit=daily_limit, actual_value=round(daily_dd_pct, 4),
                    reason=reason, severity='hard_breach',
                    drawdown_model=_dd_label(daily_model),
                    day_start_value=start_value, lowest_value=lowest_value, current_value=current_value
                )

                challenge.violation_reason = f"Daily drawdown breached ({_dd_label(daily_model)}): {daily_dd_pct:.2f}% >= {daily_limit}%"
                challenge.status = ChallengeState.UNDER_REVIEW
                challenge.monitoring_status = ChallengeState.UNDER_REVIEW
                challenge.review_required = True
                challenge.violation_reviewed = False

                log_rule(challenge.id, "daily_drawdown", Severity.VIOLATION,
                         f"Daily DD: {daily_dd_pct:.2f}% >= {daily_limit}% ({_dd_label(daily_model)})",
                         daily_dd_pct, daily_limit)

                notify_user(challenge.user_id, "Account Under Compliance Review",
                            "Your account is currently under compliance review. You will be notified once the review is complete.")

                db.session.commit()
            else:
                print(f"[DAILY DD SKIP] Unreviewed daily drawdown violation already exists #{existing.id}")

    # CHECK OVERALL DRAWDOWN
    if overall_limit > 0 and account_size > 0:
        overall_dd_pct, start_value, lowest_value, current_value = _overall_drawdown_values(challenge, overall_model, account_size)

        if overall_dd_pct >= overall_limit:
            existing = ViolationEvidence.query.filter_by(
                challenge_purchase_id=challenge.id,
                violation_type='overall_drawdown',
                is_reviewed=False
            ).first()
            
            if not existing:
                value_name = 'Balance' if overall_model == 'static' else 'Equity'
                reason = (
                    f"Overall Drawdown Breached!\n"
                    f"Drawdown Model = {_dd_label(overall_model)}\n"
                    f"Overall Limit = {overall_limit}%\n"
                    f"Actual Drawdown = {overall_dd_pct:.2f}%\n"
                    f"Account Size: ${account_size:.2f}\n"
                    f"Current {value_name}: ${current_value:.2f}"
                )

                print(f"[VIOLATION DETECTED] Overall DD: {overall_dd_pct:.2f}% >= {overall_limit}%")

                create_violation_evidence(
                    challenge=challenge, data=data,
                    violation_type='overall_drawdown', rule_name='Overall Drawdown',
                    rule_limit=overall_limit, actual_value=round(overall_dd_pct, 4),
                    reason=reason, severity='hard_breach',
                    drawdown_model=_dd_label(overall_model),
                    day_start_value=start_value, lowest_value=lowest_value, current_value=current_value
                )

                challenge.violation_reason = f"Overall drawdown breached ({_dd_label(overall_model)}): {overall_dd_pct:.2f}% >= {overall_limit}%"
                challenge.status = ChallengeState.UNDER_REVIEW
                challenge.monitoring_status = ChallengeState.UNDER_REVIEW
                challenge.review_required = True
                challenge.violation_reviewed = False

                log_rule(challenge.id, "overall_drawdown", Severity.VIOLATION,
                         f"Overall DD: {overall_dd_pct:.2f}% >= {overall_limit}% ({_dd_label(overall_model)})",
                         overall_dd_pct, overall_limit)

                notify_user(challenge.user_id, "Account Under Compliance Review",
                            "Your account is currently under compliance review. You will be notified once the review is complete.")

                db.session.commit()
            else:
                print(f"[OVERALL DD SKIP] Unreviewed overall drawdown violation already exists #{existing.id}")

# ========================================================================
# CREATE IMMUTABLE VIOLATION EVIDENCE PACKAGE
# ========================================================================

def create_violation_evidence(
    challenge, data, violation_type, rule_name, rule_limit, actual_value,
    reason, severity='hard_breach', drawdown_model=None,
    day_start_value=None, lowest_value=None, current_value=None
):
    """
    Create an IMMUTABLE evidence package when a violation is detected.
    Stores full account state, open positions, and recent trades.
    """
    try:
        account = data.get('account', {})
        cur_balance = _safe_float(account.get('balance') or data.get('balance') or challenge.current_balance)
        cur_equity = _safe_float(account.get('equity') or data.get('equity') or challenge.current_equity)
        floating_pnl = cur_equity - cur_balance if cur_balance > 0 and cur_equity > 0 else 0.0
        
        open_trades = EATrade.query.filter_by(
            challenge_purchase_id=challenge.id, status='open'
        ).all()
        
        open_positions_data = []
        for t in open_trades:
            open_positions_data.append({
                'ticket': t.ticket, 'symbol': t.symbol,
                'type': 'BUY' if t.trade_type == 0 else 'SELL',
                'lots': t.lots, 'open_price': t.open_price,
                'current_price': t.current_price, 'sl': t.sl, 'tp': t.tp,
                'floating_pnl': t.floating_pnl,
                'open_time': t.open_time.isoformat() if t.open_time else None
            })
        
        if not open_positions_data:
            for td in data.get('open_trades', []):
                open_positions_data.append({
                    'ticket': td.get('ticket'), 'symbol': td.get('symbol'),
                    'type': td.get('type'), 'lots': _safe_float(td.get('lots')),
                    'open_price': _safe_float(td.get('open_price')),
                    'current_price': _safe_float(td.get('current_price')),
                    'sl': _safe_float(td.get('sl')), 'tp': _safe_float(td.get('tp')),
                    'floating_pnl': _safe_float(td.get('floating_pnl')),
                    'open_time': td.get('open_time')
                })
        
        recent_trades = TradeHistory.query.filter_by(
            challenge_id=challenge.id, is_open=False
        ).order_by(TradeHistory.close_time.desc()).limit(10).all()
        
        recent_trades_data = []
        for t in recent_trades:
            recent_trades_data.append({
                'ticket': t.ticket, 'symbol': t.symbol, 'lots': t.lots,
                'open_price': t.open_price, 'close_price': t.close_price,
                'profit': t.profit, 'swap': t.swap, 'commission': t.commission,
                'open_time': t.open_time.isoformat() if t.open_time else None,
                'close_time': t.close_time.isoformat() if t.close_time else None
            })
        
        account_state = {
            'balance': cur_balance, 'equity': cur_equity,
            'floating_pnl': floating_pnl,
            'profit_percent': challenge.profit_percent,
            'daily_drawdown': challenge.daily_drawdown,
            'overall_drawdown': challenge.overall_drawdown,
            'trading_days': challenge.trading_days,
            'lowest_equity_today': challenge.lowest_equity_today,
            'lowest_equity_phase': challenge.lowest_equity_phase,
            'lowest_equity_lifetime': challenge.lowest_equity_lifetime,
            'day_start_equity': challenge.day_start_equity,
            'starting_balance': challenge.starting_balance,
            'account_size': _safe_float(challenge.challenge_template.account_size) if challenge.challenge_template else challenge.starting_balance
        }
        
        evidence = ViolationEvidence(
            challenge_purchase_id=challenge.id,
            violation_type=violation_type, rule_name=rule_name,
            rule_limit=rule_limit, actual_value=actual_value,
            drawdown_model=drawdown_model,
            day_start_value=day_start_value, lowest_value=lowest_value,
            current_value=current_value,
            balance=cur_balance, equity=cur_equity,
            floating_pnl=floating_pnl,
            profit_percent=challenge.profit_percent,
            daily_drawdown=challenge.daily_drawdown,
            overall_drawdown=challenge.overall_drawdown,
            trading_days=challenge.trading_days,
            reason=reason, severity=severity,
            open_positions_snapshot=open_positions_data,
            recent_trades_snapshot=recent_trades_data,
            account_snapshot_data=account_state,
            violation_timestamp=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc)
        )
        
        db.session.add(evidence)
        db.session.flush()
        
        challenge.last_violation_evidence_id = evidence.id
        
        rule_violation = RuleViolation(
            challenge_purchase_id=challenge.id,
            rule_name=rule_name, rule_value_limit=rule_limit,
            rule_value_actual=actual_value, violation_message=reason,
            severity=severity, is_hard_fail=(severity == 'hard_breach'),
            action_taken='logged', violated_at=datetime.now(timezone.utc)
        )
        db.session.add(rule_violation)
        
        print(f"[EVIDENCE] Created violation evidence #{evidence.id} for challenge {challenge.id}")
        print(f"[EVIDENCE] Open positions captured: {len(open_positions_data)}")
        print(f"[EVIDENCE] Recent trades captured: {len(recent_trades_data)}")
        
        return evidence
        
    except Exception as e:
        print(f"[EVIDENCE ERROR] Failed to create violation evidence: {e}")
        traceback.print_exc()
        return None

# ========================================================================
# AUTO-INIT STARTING BALANCE
# ========================================================================

def _ensure_starting_balance(challenge, data):
    account = data.get('account', {})
    balance = _safe_float(account.get('balance') or data.get('balance'))

    if balance <= 0:
        return

    if not challenge.starting_balance or challenge.starting_balance == 0:
        challenge.starting_balance    = balance
        challenge.highest_equity      = balance
        challenge.peak_equity         = balance
        challenge.day_start_equity    = _safe_float(account.get('equity') or balance)
        challenge.day_start_balance   = balance
        challenge.daily_start_balance = balance
        challenge.lowest_equity_today = challenge.day_start_equity
        challenge.lowest_equity_lifetime = balance
        challenge.lowest_equity_phase = balance

        if not challenge.start_date:
            challenge.start_date = datetime.now(timezone.utc)

        challenge.manipulation_check_baseline   = balance
        challenge.manipulation_baseline_set_at  = datetime.now(timezone.utc)
        print(f"[INIT] starting_balance + baseline set to {balance}")

    if not challenge.phase_start_balance or challenge.phase_start_balance == 0:
        challenge.phase_start_balance = balance
        challenge.phase_day_start_balance = balance
        challenge.phase_lowest_balance_today = balance

    if not challenge.last_verified_balance or challenge.last_verified_balance == 0:
        challenge.last_verified_balance = balance

    if not challenge.lowest_equity_lifetime:
        challenge.lowest_equity_lifetime = balance
    
    if not challenge.lowest_equity_phase:
        challenge.lowest_equity_phase = balance

    if not challenge.end_date and challenge.start_date:
        duration = 30
        if challenge.challenge_template:
            if challenge.challenge_type == 'instant':
                duration = 999
            elif challenge.current_phase == 2:
                duration = _safe_int(challenge.challenge_template.phase2_duration) or 30
            else:
                duration = _safe_int(challenge.challenge_template.phase1_duration) or 30
        challenge.end_date = challenge.start_date + timedelta(days=duration)

    db.session.commit()

# ========================================================================
# ACTIVE RULES LOADER
# ========================================================================

def get_active_rules(challenge):
    t = challenge.challenge_template
    if not t:
        return {
            'phase_name': 'Phase 1', 'profit_target': 8.0,
            'daily_loss': 5.0, 'daily_dd_type': 'equity',
            'overall_loss': 10.0, 'overall_dd_type': 'equity',
            'min_days': 5, 'duration': 30, 'leverage': None, 'weekend': True,
            'sl_mandatory_enabled': False, 'sl_grace_period_minutes': 3,
            'max_risk_per_trade_percent': 1.5,
            'activity_rule_enabled': False, 'max_inactive_days': 4,
            'max_lot_size_enabled': False, 'max_lot_size': 0.02,
            'lot_size_violation_action': 'flag',
        }

    ctype = challenge.challenge_type
    phase = challenge.current_phase

    base = {
        'sl_mandatory_enabled': getattr(t, 'sl_mandatory_enabled', False),
        'sl_grace_period_minutes': getattr(t, 'sl_grace_period_minutes', 3),
        'max_risk_per_trade_percent': getattr(t, 'max_risk_per_trade_percent', 1.5),
        'activity_rule_enabled': getattr(t, 'activity_rule_enabled', False),
        'max_inactive_days': getattr(t, 'max_inactive_days', 4),
        'max_lot_size_enabled': getattr(t, 'max_lot_size_enabled', False),
        'max_lot_size': getattr(t, 'max_lot_size', 0.02),
        'lot_size_violation_action': getattr(t, 'lot_size_violation_action', 'flag'),
    }

    if ctype == 'two_phase' and phase == 2:
        return {
            **base,
            'phase_name': 'Phase 2',
            'profit_target': _safe_float(t.phase2_target),
            'daily_loss': _safe_float(t.phase2_daily_loss),
            'daily_dd_type': getattr(t, 'phase2_daily_dd_type', 'equity') or 'equity',
            'overall_loss': _safe_float(t.phase2_overall_loss),
            'overall_dd_type': getattr(t, 'phase2_overall_dd_type', 'equity') or 'equity',
            'min_days': _safe_int(t.phase2_min_days),
            'duration': _safe_int(t.phase2_duration),
            'leverage': t.phase2_leverage,
            'weekend': getattr(t, 'weekend_trading', True),
        }
    elif ctype == 'instant':
        return {
            **base,
            'phase_name': 'Instant', 'profit_target': 0,
            'daily_loss': _safe_float(t.instant_daily_loss),
            'daily_dd_type': getattr(t, 'instant_daily_dd_type', 'equity') or 'equity',
            'overall_loss': _safe_float(t.instant_overall_loss),
            'overall_dd_type': getattr(t, 'instant_overall_dd_type', 'equity') or 'equity',
            'min_days': 0, 'duration': 365,
            'leverage': t.instant_leverage,
            'weekend': getattr(t, 'weekend_trading', True),
        }
    else:
        return {
            **base,
            'phase_name': 'Phase 1',
            'profit_target': _safe_float(t.phase1_target),
            'daily_loss': _safe_float(t.phase1_daily_loss),
            'daily_dd_type': getattr(t, 'phase1_daily_dd_type', 'equity') or 'equity',
            'overall_loss': _safe_float(t.phase1_overall_loss),
            'overall_dd_type': getattr(t, 'phase1_overall_dd_type', 'equity') or 'equity',
            'min_days': _safe_int(t.phase1_min_days),
            'duration': _safe_int(t.phase1_duration),
            'leverage': t.phase1_leverage,
            'weekend': getattr(t, 'weekend_trading', True),
        }

# ========================================================================
# TRADE HISTORY
# ========================================================================

def save_trade_history(challenge, data):
    all_trades = data.get('closed_trades', []) + data.get('open_trades', [])
    if not all_trades:
        return

    for td in all_trades:
        ticket = td.get('ticket')
        if not ticket:
            continue

        try:
            existing = TradeHistory.query.filter_by(
                challenge_id=challenge.id, ticket=ticket
            ).first()

            if existing:
                if td.get('close_time') and existing.is_open:
                    existing.close_time  = parse_datetime(td.get('close_time'))
                    existing.close_price = _safe_float(td.get('close_price'))
                    existing.profit      = _safe_float(td.get('profit'))
                    existing.swap        = _safe_float(td.get('swap'))
                    existing.commission  = _safe_float(td.get('commission'))
                    existing.is_open     = False
                elif existing.is_open:
                    existing.sl = _safe_float(td.get('sl'))
                    existing.tp = _safe_float(td.get('tp'))
            else:
                trade = TradeHistory(
                    challenge_id=challenge.id, ticket=_safe_int(ticket),
                    symbol=td.get('symbol', 'UNKNOWN'), lots=_safe_float(td.get('lots')),
                    open_price=_safe_float(td.get('open_price')),
                    close_price=_safe_float(td.get('close_price')) if td.get('close_price') else None,
                    profit=_safe_float(td.get('profit')), swap=_safe_float(td.get('swap')),
                    commission=_safe_float(td.get('commission')),
                    sl=_safe_float(td.get('sl')), tp=_safe_float(td.get('tp')),
                    open_time=parse_datetime(td.get('open_time')),
                    close_time=parse_datetime(td.get('close_time')) if td.get('close_time') else None,
                    is_open=not bool(td.get('close_time')),
                    magic_number=_safe_int(td.get('magic')),
                    comment=(td.get('comment') or '')[:200],
                )
                db.session.add(trade)

        except Exception as e:
            db.session.rollback()
            print(f"[TRADE SKIP] ticket {ticket} skipped: {e}")
            continue

    db.session.commit()

# ========================================================================
# METRICS UPDATE
# ========================================================================

def update_metrics(challenge, data):
    account     = data.get('account', {})
    cur_balance = _safe_float(account.get('balance') or data.get('balance') or challenge.current_balance)
    cur_equity  = _safe_float(account.get('equity')  or data.get('equity')  or challenge.current_equity)

    broker_time_str = account.get('terminal_time') or data.get('broker_time')
    now_utc         = parse_datetime(broker_time_str) if broker_time_str else datetime.now(timezone.utc)
    today           = now_utc.date()

    challenge.current_balance = cur_balance
    challenge.current_equity  = cur_equity
    challenge.last_heartbeat  = datetime.now(timezone.utc)

    highest_eq = _safe_float(challenge.highest_equity)
    if cur_equity > highest_eq:
        challenge.highest_equity = cur_equity
        challenge.peak_equity    = cur_equity

    lowest_life = _safe_float(challenge.lowest_equity_lifetime) if challenge.lowest_equity_lifetime else cur_equity
    if cur_equity < lowest_life:
        challenge.lowest_equity_lifetime = cur_equity

    lowest_phase = _safe_float(challenge.lowest_equity_phase) if challenge.lowest_equity_phase else cur_equity
    if cur_equity < lowest_phase:
        challenge.lowest_equity_phase = cur_equity

    current_daily_date = getattr(challenge, 'daily_start_date', None)
    if current_daily_date != today:
        challenge.daily_start_date          = today
        challenge.day_start_equity          = cur_equity
        challenge.day_start_balance         = cur_balance
        challenge.daily_start_balance       = cur_balance
        challenge.lowest_equity_today       = cur_equity
        challenge.highest_equity_today      = cur_equity
        challenge.phase_daily_start_date    = today
        challenge.phase_day_start_equity    = cur_equity
        challenge.phase_day_start_balance   = cur_balance
        challenge.phase_lowest_equity_today = cur_equity
        challenge.phase_lowest_balance_today = cur_balance
    else:
        lowest_today = _safe_float(challenge.lowest_equity_today) if challenge.lowest_equity_today else cur_equity
        if cur_equity < lowest_today:
            challenge.lowest_equity_today = cur_equity
        highest_today = _safe_float(challenge.highest_equity_today) if challenge.highest_equity_today else cur_equity
        if cur_equity > highest_today:
            challenge.highest_equity_today = cur_equity
        phase_lowest = _safe_float(challenge.phase_lowest_equity_today) if challenge.phase_lowest_equity_today else cur_equity
        if cur_equity < phase_lowest:
            challenge.phase_lowest_equity_today = cur_equity
        phase_lowest_balance = _safe_float(challenge.phase_lowest_balance_today) if challenge.phase_lowest_balance_today else cur_balance
        if cur_balance < phase_lowest_balance:
            challenge.phase_lowest_balance_today = cur_balance

    sb = _safe_float(challenge.starting_balance)
    challenge.profit_percent = ((cur_balance - sb) / sb * 100) if sb > 0 else 0.0

    psb = _safe_float(challenge.phase_start_balance) or sb
    challenge.phase_profit_percent = ((cur_balance - psb) / psb * 100) if psb > 0 else challenge.profit_percent

    account_size = _safe_float(challenge.challenge_template.account_size) if challenge.challenge_template else sb

    rules = get_active_rules(challenge)
    overall_model = rules.get('overall_dd_type', 'equity')
    overall_value = cur_balance if overall_model == 'static' else cur_equity
    if overall_value >= account_size:
        challenge.overall_drawdown = 0.0
    else:
        cash_lost = account_size - overall_value
        challenge.overall_drawdown = (cash_lost / account_size) * 100 if account_size > 0 else 0.0

    daily_model = rules.get('daily_dd_type', 'equity')
    if daily_model == 'static':
        dse = _safe_float(challenge.day_start_balance) or cur_balance
        let = _safe_float(challenge.phase_lowest_balance_today) or cur_balance
    else:
        dse = _safe_float(challenge.day_start_equity) or cur_equity
        let = _safe_float(challenge.lowest_equity_today) or cur_equity
    challenge.daily_drawdown = max(0.0, (dse - let) / dse * 100) if dse > 0 else 0.0

    if daily_model == 'static':
        pdse = _safe_float(challenge.phase_day_start_balance) or dse
        plet = _safe_float(challenge.phase_lowest_balance_today) or cur_balance
    else:
        pdse = _safe_float(challenge.phase_day_start_equity) or dse
        plet = _safe_float(challenge.phase_lowest_equity_today) or cur_equity
    challenge.phase_daily_drawdown = max(0.0, (pdse - plet) / pdse * 100) if pdse > 0 else 0.0

    has_activity = bool(data.get('closed_trades') or data.get('open_trades'))
    if has_activity:
        last = getattr(challenge, 'last_trade_date', None)
        if not last or last != today:
            challenge.trading_days           = (challenge.trading_days or 0) + 1
            challenge.phase_trading_days     = (challenge.phase_trading_days or 0) + 1
            challenge.trading_days_completed = challenge.trading_days
            challenge.last_trade_date        = today

    now = datetime.now(timezone.utc)
    if challenge.end_date:
        end = ensure_utc(challenge.end_date)
        challenge.days_remaining = max(0, (end - now).days)
    elif challenge.start_date:
        start = ensure_utc(challenge.start_date)
        duration = 30
        if challenge.challenge_template:
            if challenge.challenge_type == 'instant':
                duration = 999
            elif challenge.current_phase == 2:
                duration = _safe_int(challenge.challenge_template.phase2_duration) or 30
            else:
                duration = _safe_int(challenge.challenge_template.phase1_duration) or 30
        challenge.end_date = start + timedelta(days=duration)
        elapsed = (now - start).days
        challenge.days_remaining = max(0, duration - elapsed)
    else:
        challenge.days_remaining = 30

    _calc_distances(challenge, rules)

    challenge.last_updated   = datetime.now(timezone.utc)
    challenge.current_profit = challenge.profit_percent

    print(
        f"[METRICS] Balance: ${cur_balance:.2f} │ Equity: ${cur_equity:.2f} │ "
        f"Profit: {challenge.profit_percent:.2f}% │ "
        f"Daily DD: {challenge.daily_drawdown:.2f}% │ "
        f"Overall DD: {challenge.overall_drawdown:.2f}% │ "
        f"Lowest Eq Life: ${challenge.lowest_equity_lifetime:.2f}"
    )

    db.session.commit()

def _calc_distances(challenge, rules):
    pt = _safe_float(rules.get('profit_target'))
    if pt > 0:
        challenge.distance_to_payout = max(0.0, pt - _safe_float(challenge.phase_profit_percent))
    else:
        challenge.distance_to_payout = None

    gaps = []
    if rules.get('daily_loss'):
        g = _safe_float(rules['daily_loss']) - _safe_float(challenge.phase_daily_drawdown)
        if g > 0:
            gaps.append(g)
    if rules.get('overall_loss'):
        g = _safe_float(rules['overall_loss']) - _safe_float(challenge.overall_drawdown)
        if g > 0:
            gaps.append(g)

    challenge.distance_to_breach = min(gaps) if gaps else None

# ========================================================================
# CORE CHALLENGE RULES
# ========================================================================

def check_rules(challenge, data, rules):
    if challenge.status in (ChallengeState.PASSED, ChallengeState.FAILED, ChallengeState.FUNDED):
        return

    phase_profit  = _safe_float(challenge.phase_profit_percent)
    phase_days    = _safe_int(challenge.phase_trading_days)
    pt            = _safe_float(rules.get('profit_target'))
    min_days      = _safe_int(rules.get('min_days'))

    if pt > 0 and phase_profit >= pt:
        log_rule(challenge.id, "profit_target", Severity.SUCCESS,
                 f"Profit target hit: {phase_profit:.2f}% >= {pt}%", phase_profit, pt)
        if phase_days >= min_days:
            _handle_phase_progression(challenge)
        else:
            needed = min_days - phase_days
            log_rule(challenge.id, "min_trading_days", Severity.INFO,
                     f"Profit reached but need {needed} more trading day(s). ({phase_days}/{min_days})",
                     phase_days, min_days)

    if challenge.end_date:
        end_date_utc = ensure_utc(challenge.end_date)
        if end_date_utc and datetime.now(timezone.utc) > end_date_utc:
            if phase_profit >= pt and phase_days >= min_days:
                _handle_phase_progression(challenge)
            else:
                challenge.status            = ChallengeState.FAILED
                challenge.monitoring_status = ChallengeState.FAILED
                challenge.is_terminated     = True
                challenge.violation_reason  = f"Challenge expired on {challenge.end_date.date()}"
                log_rule(challenge.id, "challenge_expired", Severity.VIOLATION, challenge.violation_reason)
                notify_user(challenge.user_id, "Challenge Failed", challenge.violation_reason)

    db.session.commit()

def _handle_phase_progression(challenge):
    if challenge.challenge_type == 'two_phase' and challenge.current_phase == 1:
        now = datetime.now(timezone.utc)
        challenge.status = ChallengeState.PASSED
        challenge.monitoring_status = ChallengeState.PASSED
        challenge.phase1_completed_at = now
        challenge.completed_at = now
        challenge.review_required = False
        challenge.pass_reason = "Phase 1 passed. Awaiting Phase 2 request."
        log_rule(challenge.id, "phase_complete", Severity.SUCCESS, "Phase 1 complete!")
        notify_user(challenge.user_id, "Phase 1 Passed", "Congratulations! Phase 1 passed.")
    else:
        now = datetime.now(timezone.utc)
        challenge.status = ChallengeState.PASSED
        challenge.monitoring_status = ChallengeState.PASSED
        challenge.completed_at = now
        challenge.review_required = False
        if challenge.current_phase == 2:
            challenge.pass_reason = "Phase 2 passed."
            log_rule(challenge.id, "challenge_passed", Severity.SUCCESS, "Phase 2 complete.")
            notify_user(challenge.user_id, "Phase 2 Passed", "Congratulations! Phase 2 passed.")
        else:
            challenge.funded_at = now
            log_rule(challenge.id, "challenge_passed", Severity.SUCCESS, "Challenge PASSED.")
            notify_user(challenge.user_id, "Challenge Passed", "Congratulations!")
    db.session.commit()

# ========================================================================
# ANTI-CHEAT SUITE
# ========================================================================

def check_anti_cheat(challenge, data):
    account = data.get('account', {})
    cur_balance  = _safe_float(account.get('balance') or data.get('balance'))
    cur_equity   = _safe_float(account.get('equity') or data.get('equity'))
    added_risk = 0
    
    if challenge.manipulation_check_baseline and cur_balance > 0:
        diff = abs(cur_balance - challenge.manipulation_check_baseline)
        if diff > BALANCE_MANIPULATION_THRESHOLD:
            added_risk += RISK_WEIGHTS['balance_manipulation']
    
    credit = _safe_float(account.get('credit'))
    if credit > 0:
        added_risk += RISK_WEIGHTS['credit_detected']
    
    last_hb = challenge.last_heartbeat
    if last_hb:
        hb_age = (datetime.now(timezone.utc) - last_hb).total_seconds()
        if hb_age > 900:
            added_risk += RISK_WEIGHTS['ea_disconnection']
    
    if added_risk > 0:
        challenge.risk_score = min(100, (challenge.risk_score or 0) + added_risk)
        if challenge.status not in (ChallengeState.FAILED, ChallengeState.PASSED, ChallengeState.FUNDED):
            challenge.status = ChallengeState.FLAGGED
            challenge.monitoring_status = ChallengeState.UNDER_REVIEW
            challenge.review_required = True
    db.session.commit()

# ========================================================================
# STATUS & PROGRESS FINALISATION
# ========================================================================

def update_challenge_status(challenge, rules):
    legacy_map = {
        'phase1_active': ChallengeState.ACTIVE,
        'phase2_active': ChallengeState.ACTIVE,
        'pending_credentials': ChallengeState.ACTIVE,
        'breached': ChallengeState.FAILED,
    }
    if challenge.status in legacy_map:
        challenge.status = legacy_map[challenge.status]

    pt = _safe_float(rules.get('profit_target'))
    if pt > 0:
        challenge.progress_percentage = min(100.0, _safe_float(challenge.phase_profit_percent) / pt * 100)
    else:
        challenge.progress_percentage = 0.0

    now = datetime.now(timezone.utc)
    if challenge.end_date:
        end_date_utc = ensure_utc(challenge.end_date)
        challenge.days_remaining = max(0, (end_date_utc - now).days)
    elif challenge.start_date:
        start = ensure_utc(challenge.start_date)
        duration = _safe_int(rules.get('duration')) or 30
        challenge.end_date = start + timedelta(days=duration)
        challenge.days_remaining = max(0, duration - (now - start).days)
    else:
        challenge.days_remaining = 30

    score = challenge.risk_score or 0
    if score <= 30: challenge.risk_level = 'low'
    elif score <= 60: challenge.risk_level = 'medium'
    elif score <= 89: challenge.risk_level = 'high'
    else: challenge.risk_level = 'critical'

    db.session.commit()

# ========================================================================
# ADMIN CLEAR FLAG
# ========================================================================

def admin_clear_flag(challenge):
    now = datetime.now(timezone.utc)
    challenge.status = ChallengeState.ACTIVE
    challenge.monitoring_status = ChallengeState.ACTIVE
    challenge.review_required = False
    challenge.violation_reason = None
    challenge.violation_reviewed = True
    challenge.manipulation_check_baseline = _safe_float(challenge.current_balance)
    challenge.manipulation_baseline_set_at = now
    log_rule(challenge.id, "admin_clear_flag", Severity.INFO,
             f"Admin cleared flag. Baseline reset to ${challenge.current_balance:.2f}")
    db.session.commit()

# ========================================================================
# HELPER FUNCTIONS
# ========================================================================

def parse_datetime(dt_str):
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

def log_rule(challenge_id, rule_name, severity, message, current_value=None, threshold_value=None):
    try:
        current_value_clean = _safe_float(current_value, None) if current_value is not None else None
        threshold_value_clean = _safe_float(threshold_value, None) if threshold_value is not None else None
        log = RuleLog(
            challenge_id=challenge_id, rule_name=rule_name,
            severity=severity, message=str(message)[:500],
            current_value=current_value_clean, threshold_value=threshold_value_clean,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"[LOG FAIL] {e}")