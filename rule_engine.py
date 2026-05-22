"""
TRAGENE FUNDED - RULE ENGINE (COMPLETE REWRITE)
All rules implemented, fixed metrics, proper anti-cheat, dashboard-ready

CHANGES FROM PREVIOUS VERSION:
- Balance manipulation check is SKIPPED if challenge is already flagged
  (prevents re-flagging on every sync until admin clears the flag)
- When admin clears the flag, they must set `manipulation_check_baseline`
  and `manipulation_baseline_set_at` on the challenge — the engine will
  then only count trades closed AFTER that timestamp, giving a true fresh start
- All other logic is UNCHANGED
"""

from datetime import datetime, timezone, date, timedelta
from collections import defaultdict
from models import db, TradingJourney, RuleLog, TradeHistory
import traceback

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

class Severity:
    INFO      = 'info'
    WARNING   = 'warning'
    VIOLATION = 'violation'
    CRITICAL  = 'critical'
    SUCCESS   = 'success'

# How many points each anti-cheat hit adds
RISK_WEIGHTS = {
    'balance_manipulation': 50,
    'credit_detected':      40,
    'ea_disconnection':     20,
    'weekend_trading':      30,
    'leverage_abuse':       25,
    'account_reset':        50,
    'multiple_accounts':    40,
    'manual_trade_edit':    30,
    'hedging_detected':     20,
    'martingale_pattern':   25,
    'equity_spike':         35,
    'copy_trading':         45,
}

# ========================================================================
# SAFE TYPE HELPERS  ← fixes all '>' not supported / int() errors
# ========================================================================

def _safe_float(val, fallback=0.0):
    """Convert anything to float safely."""
    if val is None or val == '' or val == 'None':
        return fallback
    try:
        return float(val)
    except (ValueError, TypeError):
        return fallback

def _safe_int(val, fallback=0):
    """Convert anything to int safely, handles '1:100' format."""
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
    """
    Parse leverage from EA which may send '1:100', '100', 100, etc.
    Always returns the numeric divisor as int (e.g. 100).
    """
    s = str(val or '0').strip()
    try:
        if ':' in s:
            return int(s.split(':')[-1])
        return int(float(s)) if s else 0
    except (ValueError, TypeError):
        return 0

# ========================================================================
# TIMEZONE HELPER - COMPLETELY FIXED
# ========================================================================

def ensure_utc(dt):
    """Convert any datetime to UTC, handles naive and aware datetimes."""
    if not dt:
        return None
    try:
        if isinstance(dt, str):
            dt = parse_datetime(dt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except:
        return datetime.now(timezone.utc)

# ========================================================================
# MAIN ENTRY POINT
# ========================================================================

def process_sync(challenge, data):
    """
    Called from receiver.py after every heartbeat.
    Order matters — do not rearrange steps.
    """
    try:
        print(f"\n[RULE ENGINE] ── Challenge {challenge.id} ─────────────────────")

        # 1. Auto-initialise starting_balance on very first sync
        _ensure_starting_balance(challenge, data)

        # 2. Persist trade history
        save_trade_history(challenge, data)

        # 3. Recalculate all metrics
        update_metrics(challenge, data)

        # 4. Load rule set for current phase
        rules = get_active_rules(challenge)

        # 5. Core challenge rules (profit target, drawdowns, expiry)
        check_rules(challenge, data, rules)

        # 6. Anti-cheat suite
        check_anti_cheat(challenge, data)

        # 7. Finalise status / progress
        update_challenge_status(challenge, rules)

        print(
            f"[RULE ENGINE] Done │ Profit: {challenge.profit_percent:.2f}% │ "
            f"DD(daily): {challenge.daily_drawdown:.2f}% │ "
            f"DD(overall): {challenge.overall_drawdown:.2f}% │ "
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

        # DO NOT SAVE ENGINE ERRORS TO RULE LOG
        # only keep server console output
        
        db.session.rollback()
        
        return False

# ========================================================================
# AUTO-INIT STARTING BALANCE
# ========================================================================

def _ensure_starting_balance(challenge, data):
    """
    If starting_balance is 0 / None (first ever sync), set it from
    the account balance that just arrived.
    Also initialise peak / phase_start_balance.
    """
    account = data.get('account', {})
    balance = _safe_float(account.get('balance') or data.get('balance'))

    if balance <= 0:
        return

    if not challenge.starting_balance or challenge.starting_balance == 0:
        challenge.starting_balance    = balance
        challenge.highest_equity      = balance
        challenge.peak_equity         = balance
        challenge.day_start_equity    = _safe_float(account.get('equity') or balance)
        challenge.lowest_equity_today = challenge.day_start_equity
        print(f"[INIT] starting_balance set to {balance}")

    if not challenge.phase_start_balance or challenge.phase_start_balance == 0:
        challenge.phase_start_balance = balance

    if not challenge.last_verified_balance or challenge.last_verified_balance == 0:
        challenge.last_verified_balance = balance

    db.session.commit()

# ========================================================================
# ACTIVE RULES LOADER
# ========================================================================

def get_active_rules(challenge):
    t = challenge.challenge_template
    if not t:
        return {
            'phase_name':    'Phase 1',
            'profit_target': 8.0,
            'daily_loss':    5.0,
            'overall_loss':  10.0,
            'min_days':      5,
            'duration':      30,
            'leverage':      None,
            'weekend':       True,
        }

    ctype = challenge.challenge_type
    phase = challenge.current_phase

    if ctype == 'two_phase' and phase == 2:
        return {
            'phase_name':    'Phase 2',
            'profit_target': _safe_float(t.phase2_target),
            'daily_loss':    _safe_float(t.phase2_daily_loss),
            'overall_loss':  _safe_float(t.phase2_overall_loss),
            'min_days':      _safe_int(t.phase2_min_days),
            'duration':      _safe_int(t.phase2_duration),
            'leverage':      t.phase2_leverage,
            'weekend':       getattr(t, 'weekend_trading', True),
        }
    elif ctype == 'instant':
        return {
            'phase_name':    'Instant',
            'profit_target': 0,
            'daily_loss':    _safe_float(t.instant_daily_loss),
            'overall_loss':  _safe_float(t.instant_overall_loss),
            'min_days':      0,
            'duration':      365,
            'leverage':      t.instant_leverage,
            'weekend':       getattr(t, 'weekend_trading', True),
        }
    else:
        return {
            'phase_name':    'Phase 1',
            'profit_target': _safe_float(t.phase1_target),
            'daily_loss':    _safe_float(t.phase1_daily_loss),
            'overall_loss':  _safe_float(t.phase1_overall_loss),
            'min_days':      _safe_int(t.phase1_min_days),
            'duration':      _safe_int(t.phase1_duration),
            'leverage':      t.phase1_leverage,
            'weekend':       getattr(t, 'weekend_trading', True),
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

        existing = TradeHistory.query.filter_by(
            challenge_id=challenge.id,
            ticket=ticket
        ).first()

        if existing:
            if td.get('close_time') and existing.is_open:
                existing.close_time  = parse_datetime(td.get('close_time'))
                existing.close_price = _safe_float(td.get('close_price'))
                existing.profit      = _safe_float(td.get('profit'))
                existing.is_open     = False
        else:
            trade = TradeHistory(
                challenge_id = challenge.id,
                ticket       = _safe_int(ticket),
                symbol       = td.get('symbol', 'UNKNOWN'),
                lots         = _safe_float(td.get('lots')),
                open_price   = _safe_float(td.get('open_price')),
                close_price  = _safe_float(td.get('close_price')) if td.get('close_price') else None,
                profit       = _safe_float(td.get('profit')),
                sl           = _safe_float(td.get('sl')),
                tp           = _safe_float(td.get('tp')),
                open_time    = parse_datetime(td.get('open_time')),
                close_time   = parse_datetime(td.get('close_time')) if td.get('close_time') else None,
                is_open      = not bool(td.get('close_time')),
                magic_number = _safe_int(td.get('magic')),
                comment      = (td.get('comment') or '')[:200],
            )
            db.session.add(trade)

    db.session.commit()

# ========================================================================
# METRICS UPDATE
# ========================================================================

def update_metrics(challenge, data):
    account     = data.get('account', {})
    cur_balance = _safe_float(account.get('balance') or data.get('balance') or challenge.current_balance)
    cur_equity  = _safe_float(account.get('equity')  or data.get('equity')  or challenge.current_equity)

    # Parse broker time
    broker_time_str = account.get('terminal_time') or data.get('broker_time')
    now_utc         = parse_datetime(broker_time_str) if broker_time_str else datetime.now(timezone.utc)
    today           = now_utc.date()

    challenge.current_balance = cur_balance
    challenge.current_equity  = cur_equity
    challenge.last_heartbeat  = datetime.now(timezone.utc)

    # ── Highest equity (all-time peak) ──────────────────────────────────
    highest_eq = _safe_float(challenge.highest_equity)
    if cur_equity > highest_eq:
        challenge.highest_equity = cur_equity
        challenge.peak_equity    = cur_equity

    # ── Daily tracking ───────────────────────────────────────────────────
    if not challenge.daily_start_date or challenge.daily_start_date != today:
        challenge.daily_start_date          = today
        challenge.day_start_equity          = cur_equity
        challenge.lowest_equity_today       = cur_equity
        challenge.highest_equity_today      = cur_equity
        challenge.phase_daily_start_date    = today
        challenge.phase_day_start_equity    = cur_equity
        challenge.phase_lowest_equity_today = cur_equity
    else:
        lowest_today = _safe_float(challenge.lowest_equity_today, cur_equity)
        if cur_equity < lowest_today:
            challenge.lowest_equity_today = cur_equity
            
        highest_today = _safe_float(challenge.highest_equity_today)
        if cur_equity > highest_today:
            challenge.highest_equity_today = cur_equity
            
        phase_lowest = _safe_float(challenge.phase_lowest_equity_today, cur_equity)
        if cur_equity < phase_lowest:
            challenge.phase_lowest_equity_today = cur_equity

    # ── Profit % (from challenge start) ─────────────────────────────────
    sb = _safe_float(challenge.starting_balance)
    challenge.profit_percent = ((cur_balance - sb) / sb * 100) if sb > 0 else 0.0

    # ── Phase profit % (from phase start) ───────────────────────────────
    psb = _safe_float(challenge.phase_start_balance) or sb
    challenge.phase_profit_percent = ((cur_balance - psb) / psb * 100) if psb > 0 else challenge.profit_percent

    # ── Overall drawdown ─────────────────────────────────────────────────
    he = _safe_float(challenge.highest_equity) or cur_equity
    challenge.overall_drawdown = max(0.0, (he - cur_equity) / he * 100) if he > 0 else 0.0

    # ── Daily drawdown ───────────────────────────────────────────────────
    dse = _safe_float(challenge.day_start_equity) or cur_equity
    let = _safe_float(challenge.lowest_equity_today) or cur_equity
    challenge.daily_drawdown = max(0.0, (dse - let) / dse * 100) if dse > 0 else 0.0

    # ── Phase daily drawdown ─────────────────────────────────────────────
    pdse = _safe_float(challenge.phase_day_start_equity) or dse
    plet = _safe_float(challenge.phase_lowest_equity_today) or cur_equity
    challenge.phase_daily_drawdown = max(0.0, (pdse - plet) / pdse * 100) if pdse > 0 else 0.0

    # ── Trading days counter ─────────────────────────────────────────────
    has_activity = bool(data.get('closed_trades') or data.get('open_trades'))
    if has_activity:
        last = getattr(challenge, 'last_trade_date', None)
        if not last or last != today:
            challenge.trading_days           = (challenge.trading_days or 0) + 1
            challenge.phase_trading_days     = (challenge.phase_trading_days or 0) + 1
            challenge.trading_days_completed = challenge.trading_days
            challenge.last_trade_date        = today

    # ── Days remaining ───────────────────────────────────────────────────
    if challenge.end_date:
        remaining = (ensure_utc(challenge.end_date) - datetime.now(timezone.utc)).days
        challenge.days_remaining = max(0, remaining)
    else:
        challenge.days_remaining = 30

    # ── Distance metrics ────────────────────────────────────────────────
    rules = get_active_rules(challenge)
    _calc_distances(challenge, rules)

    challenge.last_updated   = datetime.now(timezone.utc)
    challenge.current_profit = challenge.profit_percent

    print(
        f"[METRICS] Balance: ${cur_balance:.2f} │ "
        f"Start: ${sb:.2f} │ "
        f"Profit: {challenge.profit_percent:.2f}% │ "
        f"Daily DD: {challenge.daily_drawdown:.2f}% │ "
        f"Overall DD: {challenge.overall_drawdown:.2f}%"
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
    daily_dd      = _safe_float(challenge.phase_daily_drawdown)
    overall_dd    = _safe_float(challenge.overall_drawdown)
    pt            = _safe_float(rules.get('profit_target'))
    min_days      = _safe_int(rules.get('min_days'))
    daily_limit   = _safe_float(rules.get('daily_loss'))
    overall_limit = _safe_float(rules.get('overall_loss'))

    # ── 1. Profit target check ───────────────────────────────────────────
    if pt > 0 and phase_profit >= pt:
        log_rule(challenge.id, "profit_target", Severity.SUCCESS,
                 f"Profit target hit: {phase_profit:.2f}% >= {pt}%",
                 phase_profit, pt)
        if phase_days >= min_days:
            _handle_phase_progression(challenge)
        else:
            needed = min_days - phase_days
            log_rule(challenge.id, "min_trading_days", Severity.INFO,
                     f"Profit reached but need {needed} more trading day(s). "
                     f"({phase_days}/{min_days})",
                     phase_days, min_days)

    # ── 2. Daily drawdown breach ─────────────────────────────────────────
    if daily_limit > 0 and daily_dd >= daily_limit:
        msg = f"Daily drawdown breached: {daily_dd:.2f}% >= {daily_limit}%"
        log_rule(challenge.id, "daily_drawdown", Severity.VIOLATION, msg, daily_dd, daily_limit)
        challenge.violation_reason  = msg
        challenge.monitoring_status = ChallengeState.UNDER_REVIEW
        challenge.review_required   = True
        print(f"[VIOLATION] {msg}")

    # ── 3. Overall drawdown breach ───────────────────────────────────────
    if overall_limit > 0 and overall_dd >= overall_limit:
        msg = f"Overall drawdown breached: {overall_dd:.2f}% >= {overall_limit}%"
        log_rule(challenge.id, "overall_drawdown", Severity.VIOLATION, msg, overall_dd, overall_limit)
        challenge.violation_reason  = msg
        challenge.monitoring_status = ChallengeState.UNDER_REVIEW
        challenge.review_required   = True
        print(f"[VIOLATION] {msg}")

    # ── 4. Duration expiry ───────────────────────────────────────────────
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
                log_rule(challenge.id, "challenge_expired", Severity.VIOLATION,
                         challenge.violation_reason)
                print(f"[FAILED] Challenge expired")

    db.session.commit()

def _handle_phase_progression(challenge):
    if challenge.challenge_type == 'two_phase' and challenge.current_phase == 1:
        now = datetime.now(timezone.utc)
        challenge.current_phase             = 2
        challenge.status                    = ChallengeState.ACTIVE
        challenge.monitoring_status         = ChallengeState.ACTIVE
        challenge.phase1_completed_at       = now
        challenge.phase2_started_at         = now
        challenge.phase_start_balance       = challenge.current_balance
        challenge.phase_start_equity        = challenge.current_equity
        challenge.phase_start_date          = now
        challenge.phase_trading_days        = 0
        challenge.phase_profit_percent      = 0.0
        challenge.phase_day_start_equity    = challenge.current_equity
        challenge.phase_lowest_equity_today = challenge.current_equity
        challenge.phase_daily_start_date    = now.date()
        challenge.phase_daily_drawdown      = 0.0
        t = challenge.challenge_template
        if t and t.phase2_duration:
            challenge.end_date = now + timedelta(days=_safe_int(t.phase2_duration))
        log_rule(challenge.id, "phase_complete", Severity.SUCCESS, "Phase 1 complete — moved to Phase 2!")
        print("[SUCCESS] Moved to Phase 2")
    else:
        now = datetime.now(timezone.utc)
        challenge.status            = ChallengeState.PASSED
        challenge.monitoring_status = ChallengeState.PASSED
        challenge.completed_at      = now
        challenge.funded_at         = now
        challenge.review_required   = False
        log_rule(challenge.id, "challenge_passed", Severity.SUCCESS, "Challenge PASSED! Account funded.")
        print("[SUCCESS] Challenge PASSED — account funded")

    db.session.commit()

# ========================================================================
# ANTI-CHEAT SUITE
# ========================================================================

def check_anti_cheat(challenge, data):
    """
    All 12 anti-cheat checks.

    BALANCE MANIPULATION LOGIC (updated):
    - If the challenge is currently FLAGGED (admin hasn't cleared yet),
      skip the balance manipulation check entirely to prevent spam re-flagging.
    - When admin clears the flag, they set `manipulation_check_baseline`
      to the current balance and `manipulation_baseline_set_at` to now.
    - After that, we only count trades closed AFTER `manipulation_baseline_set_at`
      so old "dirty" history doesn't re-trigger the rule — true fresh start.
    """
    account = data.get('account', {})

    # ── Safe parse all account fields ────────────────────────────────────
    cur_balance  = _safe_float(account.get('balance')     or data.get('balance'))
    cur_equity   = _safe_float(account.get('equity')      or data.get('equity'))
    floating_pnl = _safe_float(account.get('floating_pnl'))
    cur_leverage = _parse_leverage(account.get('leverage'))

    broker_time_str = account.get('terminal_time') or data.get('broker_time')
    now_utc         = parse_datetime(broker_time_str) if broker_time_str else datetime.now(timezone.utc)

    added_risk = 0
    new_flags  = []

    # ── 1. Balance Manipulation & Account Reset ──────────────────────────
    starting = _safe_float(challenge.starting_balance)

    # NEW: skip this entire block if challenge is already flagged.
    # Admin must clear the flag first before checking resumes.
    already_flagged = (
        challenge.status == ChallengeState.FLAGGED
        and challenge.review_required == True
    )

    if starting > 0 and cur_balance > 0 and not already_flagged:
        # NEW: use manipulation_check_baseline if admin set it (fresh start after clearing).
        # Falls back to starting_balance if never set.
        baseline = _safe_float(
            getattr(challenge, 'manipulation_check_baseline', None)
        ) or starting

        # NEW: only count trades closed AFTER the baseline was set.
        # If baseline was never set (first time), count all trades from the start.
        baseline_set_at = getattr(challenge, 'manipulation_baseline_set_at', None)

        all_closed_query = TradeHistory.query.filter_by(
            challenge_id=challenge.id,
            is_open=False
        )

        if baseline_set_at:
            baseline_set_at_utc = ensure_utc(baseline_set_at)
            all_closed = all_closed_query.all()
            all_closed = [
                t for t in all_closed
                if t.close_time and ensure_utc(t.close_time) > baseline_set_at_utc
            ]
        else:
            all_closed = all_closed_query.all()

        total_closed_profit = sum(_safe_float(t.profit) for t in all_closed)
        expected_balance    = baseline + total_closed_profit
        diff                = cur_balance - expected_balance  # positive = money was added

        print(
            f"[BALANCE CHECK] Baseline: ${baseline:.2f} | "
            f"Closed P&L (since baseline): ${total_closed_profit:.2f} | "
            f"Expected: ${expected_balance:.2f} | Actual: ${cur_balance:.2f} | "
            f"Diff: ${diff:.2f}"
            + (" | Fresh-start baseline active" if baseline_set_at else "")
        )

        if diff > 1.0:
            added_risk += RISK_WEIGHTS['balance_manipulation']
            new_flags.append('balance_manipulation')
            log_rule(challenge.id, "balance_manipulation", Severity.CRITICAL,
                     f"Balance top-up detected! Expected ${expected_balance:.2f} "
                     f"(baseline ${baseline:.2f} + P&L ${total_closed_profit:.2f}) "
                     f"but got ${cur_balance:.2f}. Extra: ${diff:.2f}",
                     cur_balance, expected_balance)
            print(f"[ANTI-CHEAT] BALANCE MANIPULATION: +${diff:.2f} unexplained")

        elif diff < -1.0:
            prev     = _safe_float(getattr(challenge, 'previous_balance_snapshot', None)) or starting
            drop_pct = ((prev - cur_balance) / prev * 100) if prev > 0 else 0

            if drop_pct > 80:
                added_risk += RISK_WEIGHTS['account_reset']
                new_flags.append('account_reset')
                log_rule(challenge.id, "account_reset", Severity.CRITICAL,
                         f"Account reset detected! Balance dropped {drop_pct:.1f}%: "
                         f"${prev:.2f} → ${cur_balance:.2f}",
                         cur_balance, prev)
                print(f"[ANTI-CHEAT] ACCOUNT RESET: dropped {drop_pct:.1f}%")

    elif already_flagged:
        print(
            f"[ANTI-CHEAT] Balance manipulation check SKIPPED — "
            f"challenge already flagged, waiting for admin to clear."
        )

    challenge.previous_balance_snapshot = cur_balance

    # ── 2. Credit / Bonus Abuse ──────────────────────────────────────────
    credit = _safe_float(account.get('credit'))
    if credit > 0:
        added_risk += RISK_WEIGHTS['credit_detected']
        new_flags.append('credit_detected')
        log_rule(challenge.id, "credit_detected", Severity.WARNING,
                 f"Broker credit/bonus detected: ${credit:.2f}", credit, 0)

    # ── 3. EA Disconnection ──────────────────────────────────────────────
    if challenge.last_heartbeat:
        last_hb = ensure_utc(challenge.last_heartbeat)
        if last_hb:
            secs_since = (datetime.now(timezone.utc) - last_hb).total_seconds()
            if secs_since > 300:
                added_risk += RISK_WEIGHTS['ea_disconnection']
                new_flags.append('ea_disconnection')
                challenge.ea_connected      = False
                challenge.monitoring_status = ChallengeState.OFFLINE
                log_rule(challenge.id, "ea_disconnection", Severity.WARNING,
                         f"EA offline for {secs_since:.0f}s")
            else:
                challenge.ea_connected = True
                if challenge.monitoring_status == ChallengeState.OFFLINE:
                    challenge.monitoring_status = ChallengeState.ACTIVE
    else:
        challenge.ea_connected = True

    # ── 4. Weekend Trading ───────────────────────────────────────────────
    rules           = get_active_rules(challenge)
    weekend_allowed = rules.get('weekend', True)
    if not weekend_allowed:
        has_trades = bool(data.get('open_trades') or data.get('closed_trades'))
        is_weekend = now_utc.weekday() >= 5  # Saturday=5, Sunday=6
        if is_weekend and has_trades:
            added_risk += RISK_WEIGHTS['weekend_trading']
            new_flags.append('weekend_trading')
            log_rule(challenge.id, "weekend_trading", Severity.WARNING,
                     f"Trading on weekend ({now_utc.strftime('%A %Y-%m-%d')})")

    # ── 5. Leverage Abuse ────────────────────────────────────────────────
    max_lev = _parse_leverage(rules.get('leverage'))
    cur_lev = _safe_float(cur_leverage)
    max_lev_float = _safe_float(max_lev)
    
    if max_lev_float > 0 and cur_lev > max_lev_float:
        added_risk += RISK_WEIGHTS['leverage_abuse']
        new_flags.append('leverage_abuse')
        log_rule(challenge.id, "leverage_abuse", Severity.WARNING,
                 f"Leverage {cur_lev} exceeds allowed {max_lev_float}",
                 cur_lev, max_lev_float)

    # ── 6. Hedging Detection ─────────────────────────────────────────────
    open_trades = data.get('open_trades', [])
    symbol_net  = defaultdict(float)
    symbol_cnt  = defaultdict(int)
    for td in open_trades:
        sym  = td.get('symbol', '')
        lots = _safe_float(td.get('lots'))
        side = str(td.get('type', '')).lower()
        if str(td.get('type')) == '0' or 'buy' in side:
            symbol_net[sym] += lots
        elif str(td.get('type')) == '1' or 'sell' in side:
            symbol_net[sym] -= lots
        symbol_cnt[sym] += 1

    for sym, net in symbol_net.items():
        if abs(net) < 0.001 and symbol_cnt[sym] >= 2:
            added_risk += RISK_WEIGHTS['hedging_detected']
            new_flags.append(f'hedging_{sym}')
            log_rule(challenge.id, "hedging_detected", Severity.WARNING,
                     f"Hedging on {sym}: net={net:.3f} lots with {symbol_cnt[sym]} positions open")
            break

    # ── 7. Martingale Pattern ─────────────────────────────────────────────
    recent = (
        TradeHistory.query
        .filter_by(challenge_id=challenge.id, is_open=False)
        .order_by(TradeHistory.close_time.desc())
        .limit(8).all()
    )
    if len(recent) >= 4:
        seq_lots   = [_safe_float(t.lots)   for t in reversed(recent)]
        seq_profit = [_safe_float(t.profit) for t in reversed(recent)]
        doubles = sum(
            1 for i in range(1, len(seq_lots))
            if seq_profit[i-1] < 0 and seq_lots[i] >= seq_lots[i-1] * 1.8
        )
        if doubles >= 3:
            added_risk += RISK_WEIGHTS['martingale_pattern']
            new_flags.append('martingale_pattern')
            log_rule(challenge.id, "martingale_pattern", Severity.WARNING,
                     f"Martingale: lot doubling after loss detected {doubles} times in last {len(recent)} trades")

    # ── 8. Equity Spike ───────────────────────────────────────────────────
    prev_eq  = _safe_float(getattr(challenge, 'previous_equity_snapshot',  None)) or cur_equity
    prev_bal = _safe_float(getattr(challenge, 'previous_balance_for_spike', None)) or cur_balance
    if prev_eq > 0 and prev_bal > 0:
        eq_change  = cur_equity  - prev_eq
        bal_change = cur_balance - prev_bal
        threshold  = _safe_float(challenge.starting_balance or cur_balance) * 0.02
        if eq_change > 0 and (eq_change - bal_change) > threshold:
            added_risk += RISK_WEIGHTS['equity_spike']
            new_flags.append('equity_spike')
            log_rule(challenge.id, "equity_spike", Severity.WARNING,
                     f"Equity spike: Δeq={eq_change:.2f}, Δbal={bal_change:.2f}, "
                     f"unexplained={eq_change - bal_change:.2f}")
    challenge.previous_equity_snapshot   = cur_equity
    challenge.previous_balance_for_spike = cur_balance

    # ── 9. Copy Trading / Multiple Accounts ──────────────────────────────
    open_tickets = [_safe_int(t.get('ticket')) for t in open_trades if t.get('ticket')]
    if open_tickets:
        dupes = (
            TradeHistory.query
            .filter(
                TradeHistory.ticket.in_(open_tickets),
                TradeHistory.challenge_id != challenge.id,
                TradeHistory.is_open == True
            ).all()
        )
        if dupes:
            dupe_tickets = list({d.ticket for d in dupes})
            added_risk += RISK_WEIGHTS['copy_trading']
            new_flags.append('copy_trading')
            log_rule(challenge.id, "copy_trading", Severity.CRITICAL,
                     f"Same open tickets in other challenges: {dupe_tickets[:5]}",
                     len(dupe_tickets), 0)
            added_risk += RISK_WEIGHTS['multiple_accounts']
            new_flags.append('multiple_accounts')
            log_rule(challenge.id, "multiple_accounts", Severity.WARNING,
                     f"Multiple challenges running same positions simultaneously")

    # ── 10. Manual Trade Editing ──────────────────────────────────────────
    for td in open_trades:
        ticket = td.get('ticket')
        if not ticket:
            continue
        existing = TradeHistory.query.filter_by(
            challenge_id=challenge.id, ticket=ticket, is_open=True
        ).first()
        if existing and hasattr(existing, 'sl') and hasattr(existing, 'tp'):
            sl_now = _safe_float(td.get('sl'))
            tp_now = _safe_float(td.get('tp'))
            sl_old = _safe_float(getattr(existing, 'sl'))
            tp_old = _safe_float(getattr(existing, 'tp'))
            if (sl_old != sl_now or tp_old != tp_now) and (sl_old != 0 or tp_old != 0):
                added_risk += RISK_WEIGHTS['manual_trade_edit']
                new_flags.append('manual_trade_edit')
                log_rule(challenge.id, "manual_trade_edit", Severity.WARNING,
                         f"SL/TP modified on ticket {ticket}: "
                         f"SL {sl_old}→{sl_now}, TP {tp_old}→{tp_now}")
            existing.sl = sl_now
            existing.tp = tp_now

    # ── Accumulate & escalate ─────────────────────────────────────────────
    if added_risk > 0:
        challenge.risk_score = min(100, (challenge.risk_score or 0) + added_risk)
        print(f"[ANTI-CHEAT] Flags: {new_flags} | +{added_risk} pts → Total: {challenge.risk_score}")

    score = challenge.risk_score or 0

    # Violations NEVER auto-fail — they FLAG the account for admin review.
    # Admin manually fails from dashboard.
    if added_risk > 0:
        if challenge.status not in (ChallengeState.FAILED, ChallengeState.PASSED, ChallengeState.FUNDED):
            challenge.status            = ChallengeState.FLAGGED
            challenge.monitoring_status = ChallengeState.UNDER_REVIEW
            challenge.review_required   = True
            if new_flags:
                flag_names = {
                    'balance_manipulation': 'Balance Manipulation Detected',
                    'account_reset':        'Account Reset Detected',
                    'credit_detected':      'Broker Credit/Bonus Detected',
                    'ea_disconnection':     'EA Disconnected',
                    'weekend_trading':      'Weekend Trading Attempted',
                    'leverage_abuse':       'Leverage Limit Exceeded',
                    'hedging_detected':     'Hedging Detected',
                    'martingale_pattern':   'Martingale Pattern Detected',
                    'equity_spike':         'Unexplained Equity Spike',
                    'copy_trading':         'Copy Trading Detected',
                    'multiple_accounts':    'Multiple Accounts Detected',
                    'manual_trade_edit':    'Manual Trade Modification Detected',
                }
                primary_flag = new_flags[0]
                readable = flag_names.get(primary_flag, primary_flag.replace('_', ' ').title())
                challenge.violation_reason = readable
                challenge.flagged_reason   = readable
                print(f"[FLAGGED] Challenge {challenge.id}: {readable} | Risk: {score}")

    db.session.commit()

# ========================================================================
# STATUS & PROGRESS FINALISATION
# ========================================================================

def update_challenge_status(challenge, rules):
    """
    Normalise legacy status strings, update progress_percentage,
    and refresh days_remaining for the dashboard.
    """
    legacy_map = {
        'phase1_active':       ChallengeState.ACTIVE,
        'phase2_active':       ChallengeState.ACTIVE,
        'pending_credentials': ChallengeState.ACTIVE,
        'breached':            ChallengeState.FAILED,
    }
    if challenge.status in legacy_map:
        challenge.status = legacy_map[challenge.status]

    pt = _safe_float(rules.get('profit_target'))
    if pt > 0:
        challenge.progress_percentage = min(100.0, _safe_float(challenge.phase_profit_percent) / pt * 100)
    else:
        challenge.progress_percentage = 0.0

    if challenge.end_date:
        end_date_utc = ensure_utc(challenge.end_date)
        if end_date_utc:
            rem = (end_date_utc - datetime.now(timezone.utc)).days
            challenge.days_remaining = max(0, rem)
        else:
            challenge.days_remaining = 30
    else:
        challenge.days_remaining = 30

    score = challenge.risk_score or 0
    if score <= 30:
        challenge.risk_level = 'low'
    elif score <= 60:
        challenge.risk_level = 'medium'
    elif score <= 89:
        challenge.risk_level = 'high'
    else:
        challenge.risk_level = 'critical'

    db.session.commit()

# ========================================================================
# HELPER FUNCTIONS
# ========================================================================

def parse_datetime(dt_str):
    """Parse datetime string safely with proper timezone handling."""
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

def log_rule(challenge_id, rule_name, severity, message,
             current_value=None, threshold_value=None):
    """Log a rule event safely without crashing on type conversions."""
    try:
        # Safe conversions using _safe_float
        current_value_clean   = _safe_float(current_value, None)   if current_value  is not None else None
        threshold_value_clean = _safe_float(threshold_value, None) if threshold_value is not None else None
        
        log = RuleLog(
            challenge_id    = challenge_id,
            rule_name       = rule_name,
            severity        = severity,
            message         = str(message)[:500],
            current_value   = current_value_clean,
            threshold_value = threshold_value_clean,
            created_at      = datetime.now(timezone.utc),
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"[LOG FAIL] {e}")
        # Don't let logging failure crash the rule engine