from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort, Response
from functools import wraps
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, PayoutAuditLog, FAQ, SupportTicket, TicketMessage, Payment, AdminLog, Notification, UserNotification, NotificationTemplate, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection
from datetime import datetime, timedelta, timezone
import secrets
import csv
import io
from notification_service import create_notification, notify_all_users

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

PAYOUT_ACTIVE_STATUSES = ['pending', 'under_review', 'approved']

def _admin_name(user):
    return user.get_full_name() if user else 'System'

def _notify_user(user_id, title, message, admin_id=None):
    create_notification(
        user_id,
        title,
        message,
        'system',
        admin_id=admin_id,
    )

def _notify_challenge_passed(challenge, admin_id=None):
    create_notification(
        challenge.user_id,
        'Challenge Passed',
        'Congratulations! You have successfully passed your challenge. Your funded account review process has begun.',
        'challenge',
        action_url='/user/challenges',
        icon='target',
        admin_id=admin_id,
        dedupe_key=f'challenge-passed:{challenge.id}',
    )
    try:
        from email_service import send_automation_email
        user = User.query.get(challenge.user_id)
        if user:
            send_automation_email('challenge_passed', user, challenge=challenge)
    except Exception as exc:
        print(f"[EMAIL] Challenge passed automation skipped: {exc}")

def _notify_challenge_breached(challenge, admin_id=None):
    create_notification(
        challenge.user_id,
        'Challenge Breached',
        'Unfortunately your challenge has been breached. Review your performance and prepare for your next attempt.',
        'challenge',
        action_url='/user/challenges',
        icon='warning',
        admin_id=admin_id,
        dedupe_key=f'challenge-breached:{challenge.id}',
    )
    try:
        from email_service import send_automation_email
        user = User.query.get(challenge.user_id)
        if user:
            send_automation_email('challenge_failed', user, challenge=challenge)
    except Exception as exc:
        print(f"[EMAIL] Challenge failed automation skipped: {exc}")

def _activate_progression_stage(challenge, request_type):
    now = datetime.now(timezone.utc)
    challenge.status = 'active' if request_type == 'phase2' else 'funded'
    challenge.monitoring_status = 'active'
    challenge.review_required = False
    challenge.is_terminated = False
    challenge.completed_at = None

    if request_type == 'phase2':
        challenge.current_phase = 2
        challenge.phase = 2
        challenge.phase2_started_at = now
        duration = challenge.challenge_template.phase2_duration if challenge.challenge_template else None
    else:
        challenge.current_phase = 3
        challenge.phase = 3
        challenge.funded_at = now
        duration = 365

    challenge.start_date = now
    if duration:
        challenge.end_date = now + timedelta(days=int(duration))
        challenge.days_remaining = int(duration)
    else:
        challenge.end_date = None
        challenge.days_remaining = None

    baseline_balance = float(challenge.current_balance or challenge.starting_balance or 0)
    baseline_equity = float(challenge.current_equity or challenge.starting_equity or baseline_balance)
    challenge.phase_start_balance = baseline_balance
    challenge.phase_start_equity = baseline_equity
    challenge.phase_start_date = now
    challenge.phase_trading_days = 0
    challenge.phase_profit_percent = 0.0
    challenge.phase_day_start_equity = baseline_equity
    challenge.phase_lowest_equity_today = baseline_equity
    challenge.phase_daily_start_date = now.date()
    challenge.phase_daily_drawdown = 0.0
    challenge.progress_percentage = 0.0
    challenge.current_profit = 0.0
    challenge.current_loss = 0.0
    challenge.manipulation_check_baseline = baseline_balance
    challenge.manipulation_baseline_set_at = now

def _payout_audit(payout, action, admin_user=None, notes=''):
    db.session.add(PayoutAuditLog(
        payout_id=payout.id,
        action=action,
        admin_user_id=admin_user.id if admin_user else None,
        admin_username=_admin_name(admin_user),
        notes=notes or ''
    ))

def _eligible_funded_count():
    return ChallengePurchase.query.filter(
        db.or_(
            ChallengePurchase.status.in_(['funded', 'funded_active']),
            ChallengePurchase.challenge_type == 'instant'
        ),
        ChallengePurchase.status.notin_(['failed', 'expired', 'revoked'])
    ).count()

def _payout_stats(query=None):
    q = query or Payout.query
    payouts = q.all()
    by_status = {status: 0 for status in ['pending', 'under_review', 'approved', 'rejected', 'paid']}
    for payout in payouts:
        by_status[payout.status] = by_status.get(payout.status, 0) + 1
    paid = sum(p.amount or 0 for p in payouts if p.status == 'paid')
    pending = sum(p.amount or 0 for p in payouts if p.status in PAYOUT_ACTIVE_STATUSES)
    return {
        'total': len(payouts),
        'pending': by_status.get('pending', 0),
        'under_review': by_status.get('under_review', 0),
        'approved': by_status.get('approved', 0),
        'rejected': by_status.get('rejected', 0),
        'paid': by_status.get('paid', 0),
        'total_paid': paid,
        'total_pending': pending,
        'eligible_accounts': _eligible_funded_count(),
        'average': (sum(p.amount or 0 for p in payouts) / len(payouts)) if payouts else 0
    }

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access admin panel.', 'error')
            return redirect(url_for('auth.login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('user.dashboard'))
        return f(*args, **kwargs)
    return decorated_function



@admin_bp.route('/')
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    pending_kyc = User.query.filter_by(kyc_status='submitted').count()
    approved_kyc = User.query.filter_by(kyc_status='approved').count()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    # Count open support tickets
    open_tickets = SupportTicket.query.filter_by(status='open').count()
    
    # Calculate revenue dynamic
    total_revenue = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.status.in_(['SUCCESS', 'success'])
    ).scalar() or 0

    # Calculate monthly revenue change
    now = datetime.now(timezone.utc)
    start_of_this_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 1:
        start_of_last_month = datetime(now.year - 1, 12, 1, tzinfo=timezone.utc)
    else:
        start_of_last_month = datetime(now.year, now.month - 1, 1, tzinfo=timezone.utc)

    this_month_revenue = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.status.in_(['SUCCESS', 'success']),
        Payment.created_at >= start_of_this_month
    ).scalar() or 0

    last_month_revenue = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.status.in_(['SUCCESS', 'success']),
        Payment.created_at >= start_of_last_month,
        Payment.created_at < start_of_this_month
    ).scalar() or 0

    if last_month_revenue > 0:
        revenue_change = ((this_month_revenue - last_month_revenue) / last_month_revenue) * 100
    elif this_month_revenue > 0:
        revenue_change = 100.0
    else:
        revenue_change = 0.0
    
    return render_template('admin/admin_dashboard.html', 
                         total_users=total_users,
                         pending_kyc=pending_kyc,
                         approved_kyc=approved_kyc,
                         recent_users=recent_users,
                         total_revenue=total_revenue,
                         revenue_change=revenue_change,
                         open_tickets=open_tickets)


@admin_bp.errorhandler(404)
def admin_404(error):
    return render_template('admin/404.html'), 404




# Import routes to register them with admin_bp
from . import admin_users
from . import admin_challenges
from . import admin_finance
from . import admin_engagement
from . import admin_email
