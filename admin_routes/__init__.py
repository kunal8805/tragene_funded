from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort, Response
from functools import wraps
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, PayoutAuditLog, FAQ, SupportTicket, TicketMessage, Payment, AdminLog, Notification, UserNotification, NotificationTemplate, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection, SiteSettings
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

# ========================================================================
# UPDATED admin_required - ACCEPTS BOTH SUPER ADMIN AND MODERATOR
# ========================================================================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if super admin (has user_id + is_admin)
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user and user.is_admin:
                return f(*args, **kwargs)
        
        # Check if moderator (has moderator_id)
        if 'moderator_id' in session:
            from models import Moderator
            moderator = Moderator.query.get(session['moderator_id'])
            if moderator and moderator.is_active():
                return f(*args, **kwargs)
        
        flash('Please login to access this page.', 'error')
        return redirect(url_for('auth.login'))
    return decorated_function

# ========================================================================
# MODERATOR MANAGEMENT - HELPER FUNCTIONS
# ========================================================================
from models import Moderator, ModeratorActivityLog, MODERATOR_PERMISSIONS, RESTRICTED_PERMISSIONS

def get_current_moderator():
    """Get moderator from session if exists"""
    if 'moderator_id' in session:
        return Moderator.query.get(session['moderator_id'])
    return None

def moderator_required(permission_key=None):
    """Decorator to check moderator authentication and optional permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # First check if super admin
            if 'user_id' in session:
                user = User.query.get(session['user_id'])
                if user and user.is_admin:
                    return f(*args, **kwargs)
            
            # Check moderator session
            moderator = get_current_moderator()
            if not moderator:
                flash('Please login to access this page.', 'error')
                return redirect(url_for('auth.login'))
            
            if not moderator.is_active():
                flash('Your account is currently disabled. Contact admin.', 'error')
                session.pop('moderator_id', None)
                return redirect(url_for('auth.login'))
            
            # Check specific permission if required
            if permission_key and not moderator.has_permission(permission_key):
                flash('Access denied. Insufficient permissions.', 'error')
                return redirect(url_for('admin.moderator_dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_moderator_activity(moderator_id, module, action, description=None, 
                           target_type=None, target_id=None, 
                           before_state=None, after_state=None, status='success'):
    """Securely log moderator action with context"""
    try:
        module = str(module)[:50]
        action = str(action)[:100]
        description = str(description)[:500] if description else None
        target_type = str(target_type)[:50] if target_type else None
        
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        ip = ip[:45] if ip else None
        
        user_agent = str(request.headers.get('User-Agent', ''))[:500]
        
        log = ModeratorActivityLog(
            moderator_id=moderator_id,
            module=module,
            action=action,
            description=description,
            target_type=target_type,
            target_id=target_id,
            before_state=before_state,
            after_state=after_state,
            ip_address=ip,
            user_agent=user_agent,
            status=status
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[SECURITY] Failed to log moderator activity: {e}")

def validate_permissions(permissions_dict):
    """Validate and sanitize permissions"""
    if not isinstance(permissions_dict, dict):
        return {}
    
    validated = {}
    for key in MODERATOR_PERMISSIONS:
        if key in permissions_dict:
            validated[key] = bool(permissions_dict[key])
        else:
            validated[key] = False
    
    for restricted in RESTRICTED_PERMISSIONS:
        validated[restricted] = False
    
    return validated


@admin_bp.route('/')
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    pending_kyc = User.query.filter_by(kyc_status='submitted').count()
    approved_kyc = User.query.filter_by(kyc_status='approved').count()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    open_tickets = SupportTicket.query.filter_by(status='open').count()
    
    total_revenue = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.status.in_(['SUCCESS', 'success'])
    ).scalar() or 0

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
    
    settings = SiteSettings.get_settings()
    
    return render_template('admin/admin_dashboard.html', 
                         total_users=total_users,
                         pending_kyc=pending_kyc,
                         approved_kyc=approved_kyc,
                         recent_users=recent_users,
                         total_revenue=total_revenue,
                         revenue_change=revenue_change,
                         open_tickets=open_tickets,
                         settings=settings)


@admin_bp.errorhandler(404)
def admin_404(error):
    return render_template('admin/404.html'), 404


# Import routes to register them with admin_bp
from . import admin_users
from . import admin_challenges
from . import admin_finance
from . import admin_engagement
from . import admin_email
from . import moderators