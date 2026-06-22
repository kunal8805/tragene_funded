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

@admin_bp.route('/users')
@admin_required
def admin_users():
    search_query = request.args.get('search', '')
    if search_query:
        users = User.query.filter(
            (User.first_name.ilike(f'%{search_query}%')) |
            (User.last_name.ilike(f'%{search_query}%')) |
            (User.email.ilike(f'%{search_query}%'))
        ).all()
    else:
        users = User.query.all()
    
    admin_count = User.query.filter_by(is_admin=True).count()
    return render_template('admin/users.html', users=users, admin_count=admin_count)

@admin_bp.route('/kyc')
@admin_required
def admin_kyc():
    status_filter = request.args.get('status', 'submitted')
    search_query = request.args.get('search', '')
    
    query = User.query
    
    if status_filter == 'submitted':
        query = query.filter_by(kyc_status='submitted')
    elif status_filter == 'approved':
        query = query.filter_by(kyc_status='approved')
    elif status_filter == 'rejected':
        query = query.filter_by(kyc_status='rejected')
    else:
        query = query.filter(User.kyc_status != 'pending')
    
    if search_query:
        query = query.filter(
            (User.first_name.ilike(f'%{search_query}%')) |
            (User.last_name.ilike(f'%{search_query}%')) |
            (User.email.ilike(f'%{search_query}%'))
        )
    
    kyc_users = query.all()
    
    return render_template('admin/kyc_applications.html', 
                         kyc_users=kyc_users, 
                         status_filter=status_filter)

@admin_bp.route('/kyc/<int:user_id>')
@admin_required
def admin_kyc_review(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/kyc_review.html', user=user)

@admin_bp.route('/kyc/<int:user_id>/approve')
@admin_required
def admin_approve_kyc(user_id):
    user = User.query.get_or_404(user_id)
    user.kyc_status = 'approved'
    user.kyc_notes = ''
    create_notification(
        user.id,
        'KYC Verified',
        'Congratulations! Your KYC has been successfully verified. You can now purchase challenges and participate fully on the platform.',
        'kyc',
        action_url='/challenges',
        icon='check',
        admin_id=session.get('user_id'),
        dedupe_key=f'kyc-approved:{user.id}',
    )
    db.session.commit()
    
    flash(f'KYC for {user.email} has been approved.', 'success')
    return redirect(url_for('admin.admin_kyc'))

@admin_bp.route('/kyc/<int:user_id>/reject', methods=['POST'])
@admin_required
def admin_reject_kyc(user_id):
    user = User.query.get_or_404(user_id)
    rejection_reason = request.form.get('rejection_reason', 'Document not clear')
    user.kyc_status = 'rejected'
    user.kyc_notes = rejection_reason
    create_notification(
        user.id,
        'KYC Verification Failed',
        'Unfortunately your KYC verification was not approved. Please review the rejection reason and upload updated documents.',
        'kyc',
        action_url='/kyc',
        icon='warning',
        admin_id=session.get('user_id'),
        dedupe_key=f'kyc-rejected:{user.id}:{datetime.now(timezone.utc).date().isoformat()}',
    )
    db.session.commit()
    
    flash(f'KYC for {user.email} has been rejected.', 'success')
    return redirect(url_for('admin.admin_kyc'))

@admin_bp.route('/kyc/<int:user_id>/delete')
@admin_required
def admin_delete_kyc(user_id):
    user = User.query.get_or_404(user_id)
    user.kyc_status = 'pending'
    user.id_front_url = ''
    user.id_back_url = ''
    user.document_type = ''
    user.kyc_submitted_at = None
    user.kyc_notes = ''
    db.session.commit()
    flash(f'KYC data cleared for {user.email}.', 'success')
    return redirect(url_for('admin.admin_kyc'))

@admin_bp.route('/bulk_kyc_action', methods=['POST'])
@admin_required
def admin_bulk_kyc_action():
    user_ids = request.form.getlist('user_ids')
    action = request.form.get('action')
    
    users = User.query.filter(User.id.in_(user_ids)).all()
    
    if action == 'approve':
        for user in users:
            user.kyc_status = 'approved'
            user.kyc_notes = ''
            create_notification(
                user.id,
                'KYC Verified',
                'Congratulations! Your KYC has been successfully verified. You can now purchase challenges and participate fully on the platform.',
                'kyc',
                action_url='/challenges',
                icon='check',
                admin_id=session.get('user_id'),
                dedupe_key=f'kyc-approved:{user.id}',
            )
        db.session.commit()
        flash(f'Approved {len(users)} KYC applications.', 'success')
    elif action == 'reject':
        for user in users:
            user.kyc_status = 'rejected'
            user.kyc_notes = 'Bulk rejection'
            create_notification(
                user.id,
                'KYC Verification Failed',
                'Unfortunately your KYC verification was not approved. Please review the rejection reason and upload updated documents.',
                'kyc',
                action_url='/kyc',
                icon='warning',
                admin_id=session.get('user_id'),
                dedupe_key=f'kyc-rejected:{user.id}:{datetime.now(timezone.utc).date().isoformat()}',
            )
        db.session.commit()
        flash(f'Rejected {len(users)} KYC applications.', 'success')
    elif action == 'delete':
        for user in users:
            user.kyc_status = 'pending'
            user.id_front_url = ''
            user.id_back_url = ''
            user.document_type = ''
            user.kyc_submitted_at = None
            user.kyc_notes = ''
        db.session.commit()
        flash(f'Cleared {len(users)} KYC applications.', 'success')
    
    return redirect(url_for('admin.admin_kyc'))


@admin_bp.route('/search-challenges', methods=['POST'])
@admin_required
def admin_search_challenges():
    try:
        data = request.get_json()
        search_term = data.get('search', '').strip()
        status_filter = data.get('status', 'all')
        phase_filter = data.get('phase', 'all')
        
        query = ChallengePurchase.query.join(User).join(ChallengeTemplate)
        
        if search_term:
            query = query.filter(
                (User.first_name.ilike(f'%{search_term}%')) |
                (User.last_name.ilike(f'%{search_term}%')) |
                (User.email.ilike(f'%{search_term}%')) |
                (ChallengePurchase.mt5_account.ilike(f'%{search_term}%'))
            )
        
        if status_filter != 'all':
            query = query.filter(ChallengePurchase.status == status_filter)
        
        if phase_filter != 'all':
            query = query.filter(ChallengePurchase.phase == int(phase_filter))
        
        results = query.order_by(ChallengePurchase.start_date.desc()).limit(100).all()
        
        formatted_results = []
        now_utc = datetime.now(timezone.utc)
        
        for purchase in results:
            if purchase.start_date and purchase.end_date:
                start_date = purchase.start_date.replace(tzinfo=timezone.utc) if purchase.start_date.tzinfo is None else purchase.start_date
                end_date = purchase.end_date.replace(tzinfo=timezone.utc) if purchase.end_date.tzinfo is None else purchase.end_date
                
                total_days = (end_date - start_date).days
                days_passed = (now_utc - start_date).days
                progress = min(100, max(0, (days_passed / total_days) * 100)) if total_days > 0 else 0
                days_remaining = max(0, (end_date - now_utc).days)
            else:
                progress = 0
                days_remaining = 30
            
            formatted_results.append({
                'id': purchase.id,
                'user_name': f"{purchase.user.first_name} {purchase.user.last_name}",
                'user_email': purchase.user.email,
                'mt5_account': purchase.mt5_account,
                'challenge_price': purchase.challenge_template.price,
                'challenge_name': purchase.challenge_template.name,
                'phase': purchase.phase,
                'progress': progress,
                'profit_loss': purchase.current_profit,
                'days_left': days_remaining,
                'status': purchase.status
            })
        
        return jsonify({
            'success': True,
            'results': formatted_results,
            'count': len(formatted_results)
        })
        
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@admin_bp.route('/challenge-action', methods=['POST'])
@admin_required
def admin_challenge_action():
    try:
        data = request.get_json()
        action = data.get('action')
        challenge_id = data.get('challenge_id')
        
        purchase = ChallengePurchase.query.get_or_404(challenge_id)
        
        if action == 'force_pass_phase1':
            ctype = purchase.challenge_type or 'one_phase'
            if ctype == 'two_phase':
                purchase.current_phase = 1
                purchase.status = 'passed'
                purchase.phase = 1
                purchase.phase1_completed_at = datetime.now(timezone.utc)
                purchase.completed_at = datetime.now(timezone.utc)
                _notify_challenge_passed(purchase, session.get('user_id'))
            else:
                purchase.current_phase = 3
                purchase.status = 'funded'
                purchase.phase = 3
                _notify_challenge_passed(purchase, session.get('user_id'))
            
        elif action == 'force_pass_phase2':
            purchase.current_phase = 2
            purchase.status = 'passed'
            purchase.phase = 2
            purchase.completed_at = datetime.now(timezone.utc)
            _notify_challenge_passed(purchase, session.get('user_id'))
            
        elif action == 'force_pass_all':
            purchase.current_phase = 3
            purchase.status = 'funded'
            purchase.phase = 3
            purchase.funded_at = datetime.now(timezone.utc)
            _notify_challenge_passed(purchase, session.get('user_id'))
            
        elif action == 'force_fail':
            purchase.status = 'failed'
            purchase.is_terminated = True
            purchase.credentials_revoked_at = datetime.now(timezone.utc)
            _notify_challenge_breached(purchase, session.get('user_id'))
            
        elif action.startswith('extend_'):
            days = int(action.split('_')[1])
            if purchase.end_date:
                purchase.end_date += timedelta(days=days)
                if purchase.end_date.tzinfo is not None:
                    purchase.days_remaining = (purchase.end_date - datetime.now(timezone.utc)).days
                else:
                    purchase.days_remaining = (purchase.end_date.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Action completed successfully'})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error performing challenge action: {e}")
        return jsonify({'success': False, 'message': 'Error performing action'})

@admin_bp.route('/bulk-challenge-action', methods=['POST'])
@admin_required
def admin_bulk_challenge_action():
    try:
        data = request.get_json()
        action = data.get('action')
        challenge_ids = data.get('challenge_ids', [])
        
        purchases = ChallengePurchase.query.filter(ChallengePurchase.id.in_(challenge_ids)).all()
        
        for purchase in purchases:
            if action == 'force_pass_phase1':
                ctype = purchase.challenge_type or 'one_phase'
                if ctype == 'two_phase':
                    purchase.current_phase = 1
                    purchase.status = 'passed'
                    purchase.phase = 1
                    purchase.phase1_completed_at = datetime.now(timezone.utc)
                    purchase.completed_at = datetime.now(timezone.utc)
                    _notify_challenge_passed(purchase, session.get('user_id'))
                else:
                    purchase.current_phase = 3
                    purchase.status = 'funded'
                    purchase.phase = 3
                    _notify_challenge_passed(purchase, session.get('user_id'))
                
            elif action == 'force_pass_phase2':
                purchase.current_phase = 2
                purchase.status = 'passed'
                purchase.phase = 2
                purchase.completed_at = datetime.now(timezone.utc)
                _notify_challenge_passed(purchase, session.get('user_id'))
                
            elif action == 'force_pass_all':
                purchase.current_phase = 3
                purchase.status = 'funded'
                purchase.phase = 3
                purchase.funded_at = datetime.now(timezone.utc)
                _notify_challenge_passed(purchase, session.get('user_id'))
                
            elif action == 'force_fail':
                purchase.status = 'failed'
                purchase.is_terminated = True
                purchase.credentials_revoked_at = datetime.now(timezone.utc)
                _notify_challenge_breached(purchase, session.get('user_id'))
                
            elif action.startswith('extend_'):
                days = int(action.split('_')[1])
                if purchase.end_date:
                    purchase.end_date += timedelta(days=days)
                    if purchase.end_date.tzinfo is not None:
                        purchase.days_remaining = (purchase.end_date - datetime.now(timezone.utc)).days
                    else:
                        purchase.days_remaining = (purchase.end_date.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'Action completed for {len(purchases)} challenges'})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error performing bulk challenge action: {e}")
        return jsonify({'success': False, 'message': 'Error performing bulk action'})

@admin_bp.route('/challenge-details/<int:challenge_id>')
@admin_required
def admin_challenge_details(challenge_id):
    purchase = ChallengePurchase.query.get_or_404(challenge_id)
    return render_template('admin/challenge_details.html', purchase=purchase)

@admin_bp.route('/challenge-templates')
@admin_required
def admin_challenge_templates():
    templates = ChallengeTemplate.query.all()
    return render_template('admin/challenge_templates.html', templates=templates)

@admin_bp.route('/challenge-purchases')
@admin_required
def admin_challenge_purchases():
    purchases = ChallengePurchase.query.join(User).join(ChallengeTemplate).all()
    return render_template('admin/challenge_purchases.html', purchases=purchases)

@admin_bp.route('/manage-challenges')
@admin_required
def admin_manage_challenges():
    one_phase_challenges = ChallengeTemplate.query.filter_by(challenge_type='one_phase').all()
    two_phase_challenges = ChallengeTemplate.query.filter_by(challenge_type='two_phase').all()
    instant_challenges = ChallengeTemplate.query.filter_by(challenge_type='instant').all()
    
    return render_template('admin/add_challenge.html',
                         one_phase_challenges=one_phase_challenges,
                         two_phase_challenges=two_phase_challenges,
                         instant_challenges=instant_challenges)

import re

def validate_challenge_form(data):
    # Base validation
    if float(data.get('price', 0)) <= 0:
        raise ValueError("Price must be greater than 0")
    if float(data.get('account_size', 0)) <= 0:
        raise ValueError("Account size must be greater than 0")
        
    ctype = data.get('challenge_type', 'one_phase')
    for key in [
        'phase1_daily_dd_type', 'phase1_overall_dd_type',
        'phase2_daily_dd_type', 'phase2_overall_dd_type',
        'instant_daily_dd_type', 'instant_overall_dd_type'
    ]:
        if data.get(key, 'equity') not in ['equity', 'static']:
            raise ValueError("Drawdown type must be Equity Based or Static Balance Based")
    
    def validate_leverage(lev):
        if lev and not re.match(r'^\d+:\d+$', lev):
            raise ValueError(f"Invalid leverage format '{lev}'. Must be like 1:100")
            
    def validate_percentages(target, daily, overall, phase_name):
        if target is not None and not (0 <= float(target) <= 100):
            raise ValueError(f"{phase_name} Target must be between 0 and 100")
        if daily is not None and not (0 <= float(daily) <= 100):
            raise ValueError(f"{phase_name} Daily Loss must be between 0 and 100")
        if overall is not None and not (0 <= float(overall) <= 100):
            raise ValueError(f"{phase_name} Overall Loss must be between 0 and 100")
            
    def validate_duration(min_days, duration, phase_name):
        if min_days is not None and int(min_days) < 0:
            raise ValueError(f"{phase_name} Min Trading Days cannot be negative")
        if duration is not None and int(duration) < 1:
            raise ValueError(f"{phase_name} Duration must be at least 1 day")

    # Validate based on type
    if ctype in ['one_phase', 'two_phase']:
        validate_percentages(data.get('phase1_target'), data.get('phase1_daily_loss'), data.get('phase1_overall_loss'), "Phase 1")
        validate_duration(data.get('phase1_min_days'), data.get('phase1_duration'), "Phase 1")
        validate_leverage(data.get('phase1_leverage'))
        
        if ctype == 'two_phase':
            validate_percentages(data.get('phase2_target'), data.get('phase2_daily_loss'), data.get('phase2_overall_loss'), "Phase 2")
            validate_duration(data.get('phase2_min_days'), data.get('phase2_duration'), "Phase 2")
            validate_leverage(data.get('phase2_leverage'))
            
    elif ctype == 'instant':
        validate_percentages(None, data.get('instant_daily_loss'), data.get('instant_overall_loss'), "Instant")
        if data.get('instant_min_days') is not None and int(data.get('instant_min_days', 0)) < 0:
            raise ValueError("Instant Min Trading Days cannot be negative")
        validate_leverage(data.get('instant_leverage'))

@admin_bp.route('/save-challenge', methods=['POST'])
@admin_required
def admin_save_challenge():
    try:
        challenge_id = request.form.get('challenge_id')
        
        # Validation
        validate_challenge_form(request.form)
        
        if challenge_id:
            challenge = ChallengeTemplate.query.get(challenge_id)
            if not challenge:
                flash('Challenge not found.', 'error')
                return redirect(url_for('admin.admin_manage_challenges'))
        else:
            challenge = ChallengeTemplate()
        
        challenge.name = request.form['name']
        challenge.price = int(request.form['price'])
        challenge.account_size = int(request.form['account_size'])
        
        ctype = request.form.get('challenge_type', 'one_phase')
        challenge.challenge_type = ctype
        
        # Legacy phase mapping
        if ctype == 'two_phase':
            challenge.phase = 2
        elif ctype == 'instant':
            challenge.phase = 0
        else:
            challenge.phase = 1

        # Reset all rules first
        challenge.phase1_target = None
        challenge.phase1_daily_loss = None
        challenge.phase1_daily_dd_type = 'equity'
        challenge.phase1_overall_loss = None
        challenge.phase1_overall_dd_type = 'equity'
        challenge.phase1_min_days = None
        challenge.phase1_duration = None
        challenge.phase1_leverage = None
        challenge.phase1_rules = None
        
        challenge.phase2_target = None
        challenge.phase2_daily_loss = None
        challenge.phase2_daily_dd_type = 'equity'
        challenge.phase2_overall_loss = None
        challenge.phase2_overall_dd_type = 'equity'
        challenge.phase2_min_days = None
        challenge.phase2_duration = None
        challenge.phase2_leverage = None
        challenge.phase2_rules = None
        
        challenge.instant_daily_loss = None
        challenge.instant_daily_dd_type = 'equity'
        challenge.instant_overall_loss = None
        challenge.instant_overall_dd_type = 'equity'
        challenge.instant_min_days = None
        challenge.instant_leverage = None
        challenge.instant_rules = None

        def get_float(key):
            val = request.form.get(key)
            return float(val) if val else None
            
        def get_int(key):
            val = request.form.get(key)
            return int(val) if val else None

        if ctype in ['one_phase', 'two_phase']:
            challenge.phase1_target = get_float('phase1_target')
            challenge.phase1_daily_loss = get_float('phase1_daily_loss')
            challenge.phase1_daily_dd_type = request.form.get('phase1_daily_dd_type', 'equity')
            challenge.phase1_overall_loss = get_float('phase1_overall_loss')
            challenge.phase1_overall_dd_type = request.form.get('phase1_overall_dd_type', 'equity')
            challenge.phase1_min_days = get_int('phase1_min_days')
            challenge.phase1_duration = get_int('phase1_duration')
            challenge.phase1_leverage = request.form.get('phase1_leverage')
            challenge.phase1_rules = request.form.get('phase1_rules_text', '')
            
            if ctype == 'two_phase':
                challenge.phase2_target = get_float('phase2_target')
                challenge.phase2_daily_loss = get_float('phase2_daily_loss')
                challenge.phase2_daily_dd_type = request.form.get('phase2_daily_dd_type', 'equity')
                challenge.phase2_overall_loss = get_float('phase2_overall_loss')
                challenge.phase2_overall_dd_type = request.form.get('phase2_overall_dd_type', 'equity')
                challenge.phase2_min_days = get_int('phase2_min_days')
                challenge.phase2_duration = get_int('phase2_duration')
                challenge.phase2_leverage = request.form.get('phase2_leverage')
                challenge.phase2_rules = request.form.get('phase2_rules_text', '')
                
        elif ctype == 'instant':
            challenge.instant_daily_loss = get_float('instant_daily_loss')
            challenge.instant_daily_dd_type = request.form.get('instant_daily_dd_type', 'equity')
            challenge.instant_overall_loss = get_float('instant_overall_loss')
            challenge.instant_overall_dd_type = request.form.get('instant_overall_dd_type', 'equity')
            challenge.instant_min_days = get_int('instant_min_days')
            challenge.instant_leverage = request.form.get('instant_leverage')
            challenge.instant_rules = request.form.get('instant_rules_text', '')

        challenge.user_profit_share = int(request.form.get('user_profit_share', 0))
        challenge.payout_cycle = request.form.get('payout_cycle', 'biweekly')
        challenge.weekend_trading = 'weekend_trading' in request.form
        challenge.is_active = 'is_active' in request.form
        challenge.description = request.form.get('description', '')
        
        # 🛡️ Trading Safety Rules
        challenge.sl_mandatory_enabled = 'sl_mandatory_enabled' in request.form
        challenge.sl_grace_period_minutes = int(request.form.get('sl_grace_period_minutes', 3) or 3)
        challenge.max_risk_per_trade_percent = float(request.form.get('max_risk_per_trade_percent', 1.5) or 1.5)
        challenge.activity_rule_enabled = 'activity_rule_enabled' in request.form
        challenge.max_inactive_days = int(request.form.get('max_inactive_days', 4) or 4)
        
        is_new_challenge = not challenge_id
        if is_new_challenge:
            db.session.add(challenge)
            db.session.flush()
            notify_all_users(
                'New Challenge Available',
                'A new funded challenge has been added. Explore the latest challenge options and start your evaluation today.',
                'challenge',
                action_url='/user/challenges',
                icon='fire',
                admin_id=session.get('user_id'),
                dedupe_key=f'new-challenge:{challenge.id}',
            )
        
        db.session.commit()
        
        action = "updated" if challenge_id else "created"
        flash(f'Challenge {action} successfully!', 'success')
        
    except ValueError as e:
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        print(f"Error saving challenge: {e}")
        flash('Error saving challenge. Please try again.', 'error')
    
    return redirect(url_for('admin.admin_manage_challenges'))

@admin_bp.route('/edit-challenge/<int:challenge_id>')
@admin_required
def admin_edit_challenge(challenge_id):
    challenge = ChallengeTemplate.query.get_or_404(challenge_id)
    one_phase_challenges = ChallengeTemplate.query.filter_by(challenge_type='one_phase').all()
    two_phase_challenges = ChallengeTemplate.query.filter_by(challenge_type='two_phase').all()
    instant_challenges = ChallengeTemplate.query.filter_by(challenge_type='instant').all()
    
    return render_template('admin/add_challenge.html',
                         challenge=challenge,
                         one_phase_challenges=one_phase_challenges,
                         two_phase_challenges=two_phase_challenges,
                         instant_challenges=instant_challenges)

@admin_bp.route('/delete-challenge/<int:challenge_id>')
@admin_required
def admin_delete_challenge(challenge_id):
    try:
        challenge = ChallengeTemplate.query.get_or_404(challenge_id)
        
        purchases_count = ChallengePurchase.query.filter_by(challenge_template_id=challenge_id).count()
        
        if purchases_count > 0:
            # If there are purchases, just deactivate it so it's hidden from new buyers
            challenge.is_active = False
            db.session.commit()
            flash(f'Challenge has {purchases_count} active purchases and cannot be fully deleted. It has been DEACTIVATED instead.', 'warning')
        else:
            db.session.delete(challenge)
            db.session.commit()
            flash('Challenge deleted successfully!', 'success')
            
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting challenge: {e}")
        flash('Error processing challenge deletion.', 'error')
    
    return redirect(url_for('admin.admin_manage_challenges'))

@admin_bp.route('/toggle-challenge/<int:challenge_id>')
@admin_required
def admin_toggle_challenge(challenge_id):
    try:
        challenge = ChallengeTemplate.query.get_or_404(challenge_id)
        challenge.is_active = not challenge.is_active
        db.session.commit()
        
        status = "activated" if challenge.is_active else "deactivated"
        flash(f'Challenge {status} successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        print(f"Error toggling challenge: {e}")
        flash('Error updating challenge status.', 'error')
    
    return redirect(url_for('admin.admin_manage_challenges'))


DEFAULT_RULEBOOK_SECTIONS = [
    ('Balance', 'Definition:\nBalance is the amount of money currently in your trading account excluding any open trade profits or losses.\n\nExample:\nAccount Balance = $10,000\nOpen Trade Loss = -$500\nBalance remains:\n$10,000\n\nWhy It Matters:\nMany challenge rules use balance as a reference point.'),
    ('Equity', 'Definition:\nEquity is the real-time value of your account after including all open trade profits and losses.\n\nFormula:\nEquity = Balance + Floating Profit/Loss\n\nExample:\nBalance = $10,000\nOpen Loss = -$500\nEquity = $9,500\n\nWhy It Matters:\nMany prop firms calculate drawdown using equity.'),
    ('Floating Profit', 'Definition:\nProfit from trades that are still open.\n\nThe profit has not yet been locked in because the trade has not been closed.\n\nExample:\nTrade Open\nCurrent Profit = +$250\nFloating Profit = $250'),
    ('Floating Loss', 'Definition:\nLoss from trades that are still open.\n\nExample:\nTrade Open\nCurrent Loss = -$300\nFloating Loss = $300\n\nImportant:\nFloating losses reduce equity immediately.'),
    ('Daily Drawdown', 'Definition:\nMaximum loss allowed during a single trading day.\n\nExample:\nDaily Drawdown Limit = 5%\nAccount Size = $10,000\nMaximum Daily Loss = $500\n\nIf daily loss exceeds the allowed amount, the account may be breached.'),
    ('Overall Drawdown', 'Definition:\nMaximum loss allowed during the entire challenge.\n\nExample:\nOverall Drawdown = 10%\nAccount Size = $10,000\nMaximum Loss Allowed = $1,000'),
    ('Equity-Based Drawdown', 'Definition:\nDrawdown calculated using account equity.\n\nOpen trade losses count immediately.\n\nExample:\nBalance = $10,000\nOpen Loss = -$700\nEquity = $9,300\nSystem evaluates drawdown using $9,300.\n\nImportant:\nYou can breach the challenge even while trades remain open.'),
    ('Static Drawdown', 'Definition:\nDrawdown measured against fixed account limits.\n\nExample:\nAccount Size = $10,000\nMaximum Allowed Loss = $1,000\nAccount cannot fall below $9,000.'),
    ('Margin', 'Definition:\nMoney reserved by the broker to keep positions open.\n\nThe larger the trade size, the more margin is required.\n\nWhy It Matters:\nWithout sufficient margin, new trades may not open.'),
    ('Free Margin', 'Definition:\nAvailable funds that can still be used for trading.\n\nFormula:\nFree Margin = Equity - Used Margin\n\nExample:\nEquity = $10,000\nUsed Margin = $2,000\nFree Margin = $8,000'),
    ('Leverage', 'Definition:\nLeverage allows traders to control larger positions with smaller capital.\n\nExample:\n1:100 Leverage\n$100 controls approximately $10,000 worth of market exposure.\n\nImportant:\nHigher leverage increases both profit potential and risk.'),
    ('Margin Level', 'Definition:\nShows account health.\n\nFormula:\nMargin Level = (Equity / Used Margin) x 100\n\nHigher percentage = safer account.\nLower percentage = higher liquidation risk.'),
    ('Stop Out', 'Definition:\nAutomatic closing of trades by the broker when margin levels become critically low.\n\nPurpose:\nProtect the account from going negative.'),
    ('Profit Target', 'Definition:\nPercentage gain required to pass a challenge phase.\n\nExample:\nProfit Target = 8%\nAccount Size = $10,000\nRequired Profit = $800'),
    ('Trading Days', 'Definition:\nMinimum number of trading days required before challenge completion.\n\nExample:\nMinimum Trading Days = 5\n\nEven if profit target is reached in one day, the trader may still need additional trading days to qualify.'),
]

LEGACY_RULEBOOK_CONTENT = {
    'Balance': {'Balance is the account value excluding open trade profits or losses.\n\nExample:\nAccount Balance = $10,000\nOpen Trade = -$300\nBalance remains $10,000.'},
    'Equity': {'Equity is the real-time value of your account.\n\nFormula:\nEquity = Balance + Floating Profit/Loss\n\nExample:\nBalance = $10,000\nFloating Loss = -$300\nEquity = $9,700.'},
    'Floating Profit': {'Floating profit is profit from open positions that have not yet been closed.'},
    'Floating Loss': {'Floating loss is loss from open positions that have not yet been closed. Floating losses reduce equity immediately.'},
    'Daily Drawdown': {'Daily drawdown is the maximum loss allowed during one trading day. If breached, the account may be failed or placed under review.'},
    'Overall Drawdown': {'Overall drawdown is the maximum loss allowed during the entire challenge.'},
    'Equity Based Drawdown': {
        'Equity based drawdown is calculated using current equity. Open losses count immediately.',
        'Equity based drawdown is calculated using current equity. Open losses count immediately.\n\nExample:\nBalance = $10,000\nOpen Loss = -$600\nEquity = $9,400\nThe system evaluates drawdown using $9,400.',
    },
    'Static Drawdown': {'Static drawdown is calculated from predefined balance limits. Challenge rules determine how the threshold is measured.'},
    'Margin': {'Margin is capital reserved by the broker to keep trades open.'},
    'Free Margin': {'Formula:\nFree Margin = Equity - Used Margin\n\nLow free margin may result in stop-out.'},
    'Leverage': {
        'Leverage allows larger position sizes using less capital.',
        'Leverage allows larger position sizes using less capital.\n\nExample:\n1:100 leverage means $100 controls approximately $10,000 worth of market exposure.',
    },
    'Margin Level': {'Formula:\nMargin Level = (Equity / Used Margin) x 100\n\nLow margin levels increase liquidation risk.'},
    'Stop Out': {'Stop out is when the broker automatically closes positions because margin levels have become critically low.'},
    'Profit Target': {'Profit target is the required percentage gain needed to pass a challenge phase.'},
    'Trading Days': {
        'Trading days are the minimum number of active trading days required before passing a challenge.',
        'Trading days are the minimum number of active trading days required before passing a challenge. Opening and closing trades on separate days may count toward trading day requirements depending on platform rules.',
    },
}


def ensure_default_rulebook(admin_id=None):
    existing_sections = RulebookSection.query.all()
    existing_by_title = {
        section.title.strip().lower(): section
        for section in existing_sections
    }
    changed = False
    for idx, (title, content) in enumerate(DEFAULT_RULEBOOK_SECTIONS, start=1):
        section = existing_by_title.get(title.strip().lower())
        if not section and title == 'Equity-Based Drawdown':
            section = existing_by_title.get('equity based drawdown')

        if section:
            legacy_content = LEGACY_RULEBOOK_CONTENT.get(section.title)
            if legacy_content and section.content in legacy_content:
                section.title = title
                section.content = content
                section.display_order = idx
                section.updated_at = datetime.now(timezone.utc)
                changed = True
            continue

        db.session.add(RulebookSection(
            title=title,
            content=content,
            display_order=idx,
            is_active=True,
            created_by=admin_id
        ))
        changed = True
    if changed:
        db.session.commit()


@admin_bp.route('/rulebook')
@admin_required
def admin_rulebook():
    ensure_default_rulebook(session.get('user_id'))
    search = request.args.get('search', '').strip()
    query = RulebookSection.query
    if search:
        query = query.filter(
            db.or_(
                RulebookSection.title.ilike(f'%{search}%'),
                RulebookSection.content.ilike(f'%{search}%')
            )
        )
    sections = query.order_by(RulebookSection.display_order.asc(), RulebookSection.id.asc()).all()
    return render_template('admin/rulebook_manager.html', sections=sections, search_query=search)


@admin_bp.route('/rulebook/save', methods=['POST'])
@admin_required
def admin_rulebook_save():
    try:
        section_id = request.form.get('section_id')
        section = RulebookSection.query.get(section_id) if section_id else RulebookSection(created_by=session.get('user_id'))
        if not section:
            flash('Rulebook section not found.', 'error')
            return redirect(url_for('admin.admin_rulebook'))

        section.title = request.form.get('title', '').strip()
        section.content = request.form.get('content', '').strip()
        section.display_order = int(request.form.get('display_order') or 0)
        section.is_active = 'is_active' in request.form
        section.updated_at = datetime.now(timezone.utc)

        if not section.title or not section.content:
            raise ValueError('Title and content are required.')

        db.session.add(section)
        db.session.commit()
        flash('Rulebook section saved.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        print(f"Rulebook save error: {e}")
        flash('Error saving rulebook section.', 'error')
    return redirect(url_for('admin.admin_rulebook'))


@admin_bp.route('/rulebook/<int:section_id>/toggle')
@admin_required
def admin_rulebook_toggle(section_id):
    section = RulebookSection.query.get_or_404(section_id)
    section.is_active = not section.is_active
    section.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('Rulebook section status updated.', 'success')
    return redirect(url_for('admin.admin_rulebook'))


@admin_bp.route('/rulebook/<int:section_id>/delete', methods=['POST'])
@admin_required
def admin_rulebook_delete(section_id):
    section = RulebookSection.query.get_or_404(section_id)
    db.session.delete(section)
    db.session.commit()
    flash('Rulebook section deleted.', 'success')
    return redirect(url_for('admin.admin_rulebook'))


@admin_bp.route('/rulebook/reorder', methods=['POST'])
@admin_required
def admin_rulebook_reorder():
    for section in RulebookSection.query.all():
        value = request.form.get(f'order_{section.id}')
        if value is not None:
            section.display_order = int(value or 0)
            section.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('Rulebook order updated.', 'success')
    return redirect(url_for('admin.admin_rulebook'))

@admin_bp.route('/ban_user/<int:user_id>')
@admin_required
def admin_ban_user(user_id):
    user = User.query.get(user_id)
    if user and not user.is_admin:
        user.is_banned = True
        db.session.commit()
        flash(f'User {user.email} has been banned.', 'success')
    else:
        flash('Cannot ban admin users.', 'error')
    return redirect(request.referrer or url_for('admin.admin_users'))

@admin_bp.route('/unban_user/<int:user_id>')
@admin_required
def admin_unban_user(user_id):
    user = User.query.get(user_id)
    if user and not user.is_admin:
        user.is_banned = False
        db.session.commit()
        flash(f'User {user.email} has been unbanned.', 'success')
    else:
        flash('Cannot modify admin users.', 'error')
    return redirect(request.referrer or url_for('admin.admin_users'))

@admin_bp.route('/verify_phone/<int:user_id>')
@admin_required
def admin_verify_phone(user_id):
    user = User.query.get_or_404(user_id)
    user.phone_verified = True
    user.phone_verification_code = None
    db.session.commit()
    flash(f'Phone number for {user.email} marked as verified.', 'success')
    return redirect(request.referrer or url_for('admin.admin_users'))

@admin_bp.route('/bulk_action', methods=['POST'])
@admin_required
def admin_bulk_action():
    user_ids = request.form.getlist('user_ids')
    action = request.form.get('action')
    
    users = User.query.filter(User.id.in_(user_ids), User.is_admin == False).all()
    
    if action == 'ban':
        for user in users:
            user.is_banned = True
        db.session.commit()
        flash(f'Banned {len(users)} users.', 'success')
    elif action == 'unban':
        for user in users:
            user.is_banned = False
        db.session.commit()
        flash(f'Unbanned {len(users)} users.', 'success')
    elif action == 'delete':
        for user in users:
            db.session.delete(user)
        db.session.commit()
        flash(f'Deleted {len(users)} users.', 'success')
    
    return redirect(url_for('admin.admin_users'))

@admin_bp.route('/payments')
@admin_required
def admin_payments():
    from models import Payment  # Add this import
    
    status_filter = request.args.get('status', 'all')
    search_query = request.args.get('search', '')
    
    # Calculate stats
    total_revenue = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.status == 'SUCCESS'
    ).scalar() or 0
    total_revenue_legacy = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.status == 'success'
    ).scalar() or 0
    total_revenue += total_revenue_legacy
    
    successful_payments = Payment.query.filter(Payment.status.ilike('success')).count()
    pending_payments = Payment.query.filter(Payment.status.ilike('pending')).count()
    failed_payments = Payment.query.filter(Payment.status.ilike('failed')).count()
    refund_eligible_count = 0
    
    return render_template('admin/payments.html',
                         total_revenue=total_revenue,
                         successful_payments=successful_payments,
                         pending_payments=pending_payments,
                         failed_payments=failed_payments,
                         refund_eligible_count=refund_eligible_count,
                         status_filter=status_filter,
                         search_query=search_query)

@admin_bp.route('/api/payments', methods=['POST'])
@admin_required
def admin_api_payments():
    from models import Payment, User
    
    data = request.get_json() or {}
    search = data.get('search', '').strip()
    status = data.get('status', 'all')
    method = data.get('method', 'all')
    refund = data.get('refund', 'all')
    date_filter = data.get('date', '')
    page = max(1, int(data.get('page', 1)))
    per_page = min(100, int(data.get('per_page', 20)))
    
    query = Payment.query.join(User)
    
    if search:
        query = query.filter(
            (User.first_name.ilike(f'%{search}%')) |
            (User.last_name.ilike(f'%{search}%')) |
            (User.email.ilike(f'%{search}%')) |
            (Payment.payment_id.ilike(f'%{search}%')) |
            (Payment.cf_order_id.ilike(f'%{search}%'))
        )
    
    if status != 'all':
        query = query.filter(Payment.status.ilike(status))
        
    if method != 'all':
        query = query.filter(Payment.payment_method.ilike(f'%{method}%'))
        
    if date_filter:
        try:
            target_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Payment.created_at) == target_date)
        except ValueError:
            pass
            
    pagination = query.order_by(Payment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    results = []
    for p in pagination.items:
        challenge_name = p.challenge_purchase.challenge_template.name if p.challenge_purchase and p.challenge_purchase.challenge_template else "N/A"
        mt5_login = p.challenge_purchase.mt5_login if p.challenge_purchase else "N/A"
        results.append({
            'db_id': p.id,
            'id': p.payment_id,
            'cf_order_id': p.cf_order_id or '',
            'cf_payment_id': p.cf_payment_id or '',
            'user': {
                'id': p.user.id if p.user else '',
                'name': p.user.get_full_name() if p.user else "Deleted User",
                'email': p.user.email if p.user else ""
            },
            'challenge': challenge_name,
            'expected_amount': p.expected_amount,
            'amount': p.amount or p.amount,
            'currency': p.currency,
            'method': p.payment_method,
            'status': p.status,
            'gateway_status': p.gateway_status or '',
            'gateway_message': p.gateway_message or '',
            'date': p.created_at.strftime('%Y-%m-%d %H:%M:%S') if p.created_at else '',
            'updated_at': p.updated_at.strftime('%Y-%m-%d %H:%M:%S') if p.updated_at else '',
            'mt5Account': mt5_login,
            'ip_address': p.ip_address or '',
            'user_agent': p.user_agent or '',
            'refund_eligible': False,
            'refund_status': 'none',
            'refund_verified_by': p.refund_verified_by,
            'refund_processed_at': '',
            'notes': p.notes or ''
        })
    total_revenue = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.status == 'SUCCESS'
    ).scalar() or 0
    total_revenue_legacy = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
        Payment.status == 'success'
    ).scalar() or 0
    total_revenue += total_revenue_legacy
    
    stats = {
        'total_revenue': total_revenue,
        'successful_payments': Payment.query.filter(Payment.status.ilike('success')).count(),
        'pending_payments': Payment.query.filter(Payment.status.ilike('pending')).count(),
        'failed_payments': Payment.query.filter(Payment.status.ilike('failed')).count(),
        'refund_eligible_count': 0
    }
        
    return jsonify({
        'success': True,
        'payments': results,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'stats': stats
    })


@admin_bp.route('/settings')
@admin_required
def admin_settings():
    return render_template('admin/settings.html')

@admin_bp.route('/api/users')
@admin_required
def api_users():
    """Return paginated JSON for admin users list with filters."""
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except (ValueError, TypeError):
        page = 1
    
    try:
        per_page = min(max(int(request.args.get('per_page', 20)), 10), 100)
    except (ValueError, TypeError):
        per_page = 20
        
    search = request.args.get('search', '').strip()
    query = User.query
    if search:
        like = f"%{search}%"
        query = query.filter(
            (User.first_name.ilike(like)) |
            (User.last_name.ilike(like)) |
            (User.email.ilike(like)) |
            (User.phone.ilike(like))
        )
    account_status = request.args.get('account_status', 'all')
    if account_status != 'all':
        if account_status == 'active':
            query = query.filter(User.is_active == True)
        elif account_status == 'banned':
            query = query.filter(User.is_banned == True)
        elif account_status == 'new':
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            query = query.filter(User.created_at >= week_ago)
    kyc_status = request.args.get('kyc_status', 'all')
    if kyc_status != 'all':
        query = query.filter(User.kyc_status == kyc_status)
        
    sort = request.args.get('sort', 'newest')
    if sort == 'oldest':
        query = query.order_by(User.created_at.asc())
    else:
        query = query.order_by(User.created_at.desc())
        
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    users_data = []
    for u in pagination.items:
        users_data.append({
            'id': u.id,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'phone': u.phone or 'N/A',
            'city': getattr(u, 'city', 'N/A'),
            'state': getattr(u, 'state', 'N/A'),
            'country': getattr(u, 'country', 'N/A'),
            'status': 'banned' if u.is_banned else 'active',
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'kyc_status': getattr(u, 'kyc_status', 'N/A'),
        })
    return jsonify({
        'success': True,
        'users': users_data,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': pagination.page,
    })


# Admin 404 error handler
@admin_bp.errorhandler(404)
def admin_404(error):
    return render_template('admin/404.html'), 404


@admin_bp.route('/user/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    user = User.query.get(user_id)
    if not user:
        abort(404)
    challenges = getattr(user, 'challenge_purchases', []) if hasattr(user, 'challenge_purchases') else []
    payments = getattr(user, 'payments', []) if hasattr(user, 'payments') else []
    support_tickets = getattr(user, 'support_tickets', []) if hasattr(user, 'support_tickets') else []
    payouts = getattr(user, 'payouts', []) if hasattr(user, 'payouts') else []
    
    total_spent = sum(p.amount for p in payments if p.status.upper() == 'SUCCESS')
    total_purchases = len([p for p in payments if p.status.upper() == 'SUCCESS'])
    total_payouts = sum(p.amount for p in payouts if p.status.upper() == 'SUCCESS' or p.status.upper() == 'PAID')
    
    referrals = []
    return render_template('admin/user_detail.html', user=user,
                           challenges=challenges, payments=payments,
                           support_tickets=support_tickets, referrals=referrals,
                           total_spent=total_spent, total_purchases=total_purchases,
                           total_payouts=total_payouts)


# Helper function for challenges dashboard
def get_challenges_dashboard_data():
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    expiring_threshold = now_utc + timedelta(days=3)

    total_revenue = db.session.query(db.func.sum(ChallengeTemplate.price)).filter(
        ChallengePurchase.challenge_template_id == ChallengeTemplate.id,
        ChallengePurchase.status.in_(['active', 'passed', 'failed', 'pending_credentials'])
    ).scalar() or 0
    
    total_purchases = ChallengePurchase.query.count()
    today_purchases = ChallengePurchase.query.filter(ChallengePurchase.purchase_date >= today_start).count()
    
    active_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.status.in_(['active', 'funded'])
    ).count()
    passed_phase1 = ChallengePurchase.query.filter_by(status='passed', current_phase=1).count()
    passed_phase2 = ChallengePurchase.query.filter_by(status='passed', current_phase=2).count()
    funded_accounts = ChallengePurchase.query.filter_by(status='funded').count()
    failed_accounts = ChallengePurchase.query.filter(
        ChallengePurchase.status.in_(['failed', 'breached'])
    ).count()
    pending_phase2_requests = ProgressionRequest.query.filter_by(request_type='phase2', status='pending').count()
    pending_funded_requests = ProgressionRequest.query.filter_by(request_type='funded', status='pending').count()
    approved_requests = ProgressionRequest.query.filter_by(status='approved').count()
    declined_requests = ProgressionRequest.query.filter_by(status='declined').count()
    expiring_soon = ChallengePurchase.query.filter(
        ChallengePurchase.status.in_(['active', 'funded']),
        ChallengePurchase.end_date <= expiring_threshold,
        ChallengePurchase.end_date >= now_utc
    ).count()
    
    pending_payouts = db.session.query(db.func.sum(Payout.amount)).filter(
        Payout.status == 'pending'
    ).scalar() or 0
    payout_eligible = Payout.query.filter_by(status='pending').count()
    
    return {
        'total_revenue': total_revenue,
        'total_purchases': total_purchases,
        'today_purchases': today_purchases,
        'pending_payouts': pending_payouts,
        'active_challenges': active_challenges,
        'passed_phase1': passed_phase1,
        'passed_phase2': passed_phase2,
        'funded_accounts': funded_accounts,
        'failed_accounts': failed_accounts,
        'pending_phase2_requests': pending_phase2_requests,
        'pending_funded_requests': pending_funded_requests,
        'approved_requests': approved_requests,
        'declined_requests': declined_requests,
        'expiring_soon': expiring_soon,
        'payout_eligible': payout_eligible
    }

@admin_bp.route('/payment/<int:payment_id>/mark-refund', methods=['POST'])
@admin_required
def admin_mark_refund(payment_id):
    from models import Payment, AdminAuditLog
    payment = Payment.query.get_or_404(payment_id)
    
    if payment.status.lower() != 'success':
        return jsonify({'success': False, 'message': 'Cannot refund failed payment.'})
        
    audit = AdminAuditLog(
        admin_id=session.get('user_id'),
        action='marked_refund_eligible',
        payment_id=payment.id,
        old_value='False',
        new_value='True',
        ip_address=request.remote_addr
    )
    db.session.add(audit)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Payment marked as refund eligible.'})

@admin_bp.route('/payments/<int:payment_id>/refund', methods=['POST'])
@admin_required
def refund_payment(payment_id):
    from models import Payment, AdminAuditLog
    payment = Payment.query.get_or_404(payment_id)
    
    # refund not implemented
    return jsonify({'success': False, 'message': 'Payment must be marked eligible first.'})

@admin_bp.route('/payments/<int:payment_id>/update-status', methods=['POST'])
@admin_required
def update_payment_status(payment_id):
    from models import Payment
    
    payment = Payment.query.get_or_404(payment_id)
    new_status = request.form.get('status')
    
    if new_status in ['pending', 'success', 'failed', 'refunded']:
        payment.status = new_status
        db.session.commit()
        flash(f'Payment status updated to {new_status}.', 'success')
    else:
        flash('Invalid status.', 'error')
    
    return redirect(url_for('admin.admin_payments'))

@admin_bp.route('/payments/export')
@admin_required
def export_payments():
    from models import Payment
    
    payments = Payment.query.join(User).order_by(Payment.created_at.desc()).all()
    
    flash('Export feature would generate CSV file with payment data.', 'info')
    return redirect(url_for('admin.admin_payments'))


@admin_bp.route('/progression-requests')
@admin_required
def admin_progression_requests():
    requests_query = ProgressionRequest.query.join(ProgressionRequest.user).join(ProgressionRequest.challenge_purchase)
    status = request.args.get('status', '').strip()
    if status:
        requests_query = requests_query.filter(ProgressionRequest.status == status)
    progression_requests = requests_query.order_by(ProgressionRequest.created_at.desc()).all()
    stats = {
        'pending_phase2': ProgressionRequest.query.filter_by(request_type='phase2', status='pending').count(),
        'pending_funded': ProgressionRequest.query.filter_by(request_type='funded', status='pending').count(),
        'approved': ProgressionRequest.query.filter_by(status='approved').count(),
        'declined': ProgressionRequest.query.filter_by(status='declined').count()
    }
    return render_template('admin/progression_requests.html', progression_requests=progression_requests, stats=stats, status=status)


@admin_bp.route('/progression-requests/<int:request_id>/<action>', methods=['POST'])
@admin_required
def admin_progression_request_action(request_id, action):
    progression_request = ProgressionRequest.query.get_or_404(request_id)
    admin_user = User.query.get(session['user_id'])
    now = datetime.now(timezone.utc)

    if progression_request.status != 'pending':
        flash('Only pending progression requests can be updated.', 'error')
        return redirect(url_for('admin.admin_progression_requests'))

    challenge = progression_request.challenge_purchase
    if action == 'approve':
        progression_request.status = 'approved'
        progression_request.approved_at = now
        _activate_progression_stage(challenge, progression_request.request_type)
        if progression_request.request_type == 'phase2':
            title = 'Phase 2 Request Approved'
            message = (
                'Your request has been approved. Your new trading account is currently being prepared. '
                'You will receive your MT5 credentials via your verified email address within 24 hours. '
                'Please do not trade on your previous account.'
            )
        else:
            title = 'Funded Request Approved'
            message = (
                'Your funded account request has been approved. Your funded account credentials will be sent '
                'to your verified email address within 24 hours.'
            )
        _notify_user(progression_request.user_id, title, message, admin_user.id)
        flash('Progression request approved.', 'success')
    elif action == 'decline':
        reason = request.form.get('admin_reason', '').strip()
        if not reason:
            flash('Decline reason is required.', 'error')
            return redirect(url_for('admin.admin_progression_requests'))
        progression_request.status = 'declined'
        progression_request.admin_reason = reason
        progression_request.declined_at = now
        title = 'Phase 2 Request Declined' if progression_request.request_type == 'phase2' else 'Funded Request Declined'
        _notify_user(progression_request.user_id, title, f'Request Declined. Reason: {reason}', admin_user.id)
        flash('Progression request declined.', 'success')
    else:
        abort(404)

    db.session.commit()
    return redirect(url_for('admin.admin_progression_requests'))

@admin_bp.route('/payouts')
@admin_required
def admin_payouts():
    payouts = Payout.query.order_by(Payout.created_at.desc()).all()
    stats = _payout_stats(Payout.query)
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    paid_payouts = [p for p in payouts if p.status == 'paid']
    approved_payouts = [p for p in payouts if p.status in ['approved', 'paid']]
    rejected_payouts = [p for p in payouts if p.status == 'rejected']
    analytics = {
        'week_paid': sum(p.amount or 0 for p in paid_payouts if p.paid_at and (p.paid_at.replace(tzinfo=timezone.utc) if p.paid_at.tzinfo is None else p.paid_at) >= week_start),
        'month_paid': sum(p.amount or 0 for p in paid_payouts if p.paid_at and (p.paid_at.replace(tzinfo=timezone.utc) if p.paid_at.tzinfo is None else p.paid_at) >= month_start),
        'all_paid': sum(p.amount or 0 for p in paid_payouts),
        'approved_amount': sum(p.amount or 0 for p in approved_payouts),
        'paid_amount': sum(p.amount or 0 for p in paid_payouts),
        'rejected_amount': sum(p.amount or 0 for p in rejected_payouts),
        'average_size': stats['average'],
        'pending_liability': stats['total_pending'],
        'top_traders': db.session.query(User.first_name, User.last_name, db.func.count(Payout.id).label('count'), db.func.coalesce(db.func.sum(Payout.amount), 0).label('amount'))
            .join(Payout, Payout.user_id == User.id)
            .group_by(User.id)
            .order_by(db.func.count(Payout.id).desc())
            .limit(5).all()
    }
    return render_template('admin/payouts.html', payouts=payouts, stats=stats, analytics=analytics)

@admin_bp.route('/payouts/history')
@admin_required
def admin_payout_history():
    query = Payout.query.join(User, Payout.user_id == User.id).join(ChallengePurchase, Payout.challenge_purchase_id == ChallengePurchase.id)
    username = request.args.get('username', '').strip()
    challenge = request.args.get('challenge', '').strip()
    status = request.args.get('status', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    amount_min = request.args.get('amount_min', '').strip()
    amount_max = request.args.get('amount_max', '').strip()

    if username:
        query = query.filter(db.or_(User.first_name.ilike(f'%{username}%'), User.last_name.ilike(f'%{username}%'), User.email.ilike(f'%{username}%'), Payout.username_snapshot.ilike(f'%{username}%')))
    if challenge:
        query = query.filter(Payout.challenge_name_snapshot.ilike(f'%{challenge}%'))
    if status:
        query = query.filter(Payout.status == status)
    if date_from:
        query = query.filter(Payout.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Payout.created_at < datetime.fromisoformat(date_to) + timedelta(days=1))
    if amount_min:
        query = query.filter(Payout.amount >= float(amount_min))
    if amount_max:
        query = query.filter(Payout.amount <= float(amount_max))

    payouts = query.order_by(Payout.created_at.desc()).all()
    return render_template('admin/payout_history.html', payouts=payouts, stats=_payout_stats(query))

@admin_bp.route('/payouts/export')
@admin_required
def export_payouts():
    payouts = Payout.query.order_by(Payout.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Request Date', 'Username', 'Challenge', 'Account Size', 'Account Type', 'Requested Amount', 'Status', 'Payment Method', 'Approval Date', 'Payment Date', 'Transaction Reference', 'Rejection Reason'])
    for payout in payouts:
        writer.writerow([
            payout.created_at.strftime('%Y-%m-%d %H:%M') if payout.created_at else '',
            payout.username_snapshot or (payout.user.get_full_name() if payout.user else ''),
            payout.challenge_name_snapshot,
            payout.account_size_snapshot,
            payout.account_type_snapshot,
            payout.amount,
            payout.status,
            payout.payment_method,
            payout.approved_at.strftime('%Y-%m-%d %H:%M') if payout.approved_at else '',
            payout.paid_at.strftime('%Y-%m-%d %H:%M') if payout.paid_at else '',
            payout.transaction_id or '',
            payout.rejection_reason or ''
        ])
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=payouts.csv'})

@admin_bp.route('/payouts/<int:payout_id>/<action>', methods=['POST'])
@admin_required
def admin_payout_action(payout_id, action):
    payout = Payout.query.get_or_404(payout_id)
    admin_user = User.query.get(session['user_id'])
    now = datetime.now(timezone.utc)

    if action == 'review':
        if payout.status != 'pending':
            flash('Only pending requests can be moved to review.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        payout.status = 'under_review'
        payout.reviewed_at = now
        _payout_audit(payout, 'under_review', admin_user, 'Moved to review.')
        _notify_user(payout.user_id, 'Payout under review', f'Your ${payout.amount:.2f} payout request is now under review.', admin_user.id)
    elif action == 'approve':
        if payout.status not in ['pending', 'under_review']:
            flash('Only pending or under review requests can be approved.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        expected = request.form.get('expected_payment_time', '').strip()
        if not expected:
            flash('Expected payment time is required.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        payout.status = 'approved'
        payout.approved_at = now
        payout.expected_payment_time = expected
        _payout_audit(payout, 'approved', admin_user, f'Expected payment: {expected}')
        create_notification(
            payout.user_id,
            'Payout Approved',
            'Your payout request has been approved and will be processed shortly.',
            'payout',
            action_url='/user/payouts',
            icon='dollar',
            admin_id=admin_user.id,
            dedupe_key=f'payout-approved:{payout.id}',
        )
    elif action == 'reject':
        reason = request.form.get('rejection_reason', '').strip()
        if not reason:
            flash('Rejection reason is required.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        payout.status = 'rejected'
        payout.rejection_reason = reason
        payout.reviewed_at = now
        _payout_audit(payout, 'rejected', admin_user, reason)
        create_notification(
            payout.user_id,
            'Payout Request Declined',
            'Your payout request could not be approved. Please review the reason provided and submit a new request if necessary.',
            'payout',
            action_url='/user/payouts',
            icon='warning',
            admin_id=admin_user.id,
            dedupe_key=f'payout-rejected:{payout.id}',
        )
    elif action == 'paid':
        if payout.status != 'approved':
            flash('Only approved requests can be marked as paid.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        tx_ref = request.form.get('transaction_id', '').strip()
        notes = request.form.get('admin_notes', '').strip()
        payment_date = request.form.get('payment_date', '').strip()
        if not tx_ref:
            flash('Transaction reference is required.', 'error')
            return redirect(url_for('admin.admin_payouts'))
        payout.status = 'paid'
        payout.transaction_id = tx_ref
        payout.admin_notes = notes
        payout.paid_at = datetime.fromisoformat(payment_date) if payment_date else now
        payout.payout_date = payout.paid_at
        _payout_audit(payout, 'paid', admin_user, notes or tx_ref)
        _notify_user(payout.user_id, 'Payout paid successfully', f'Your ${payout.amount:.2f} payout was paid successfully.', admin_user.id)
    else:
        abort(404)

    db.session.commit()
    flash('Payout updated successfully.', 'success')
    return redirect(request.referrer or url_for('admin.admin_payouts'))

# ===== CHALLENGE MANAGEMENT ROUTES =====

@admin_bp.route('/challenges')
@admin_required
def admin_challenges():
    """List all challenge purchases with search"""
    search_query = request.args.get('search', '').strip()
    
    query = db.session.query(ChallengePurchase).join(User).join(ChallengeTemplate)
    
    if search_query:
        if search_query.isdigit():
            query = query.filter(ChallengePurchase.serial_no == int(search_query))
        else:
            query = query.filter(
                (User.email.ilike(f'%{search_query}%')) |
                (User.first_name.ilike(f'%{search_query}%')) |
                (User.last_name.ilike(f'%{search_query}%'))
            )
    
    challenges = query.order_by(ChallengePurchase.purchase_date.desc()).all()
    stats = get_challenges_dashboard_data()
    
    return render_template('admin/challenge_list.html', 
                         challenges=challenges,
                         search_query=search_query,
                         stats=stats)

@admin_bp.route('/challenges/<int:challenge_id>')
@admin_required
def admin_challenge_detail(challenge_id):
    """View challenge detail with code + token"""
    challenge = ChallengePurchase.query.get_or_404(challenge_id)
    
    return render_template('admin/challenge_detail.html', 
                         challenge=challenge)

# ===== ADMIN FAQ MANAGEMENT =====
@admin_bp.route('/faq')
@admin_required
def admin_faq():
    faqs = FAQ.query.order_by(FAQ.category, FAQ.created_at.desc()).all()
    return render_template('admin/faq_manage.html', faqs=faqs)

@admin_bp.route('/faq/create', methods=['GET', 'POST'])
@admin_required
def admin_faq_create():
    if request.method == 'POST':
        question = request.form.get('question')
        answer = request.form.get('answer')
        category = request.form.get('category')
        is_pinned = 'is_pinned' in request.form
        
        faq = FAQ(
            question=question,
            answer=answer,
            category=category,
            is_pinned=is_pinned
        )
        db.session.add(faq)
        db.session.commit()
        
        flash('FAQ created successfully!', 'success')
        return redirect(url_for('admin.admin_faq'))
    
    return render_template('admin/faq_form.html')

@admin_bp.route('/faq/edit/<int:faq_id>', methods=['GET', 'POST'])
@admin_required
def admin_faq_edit(faq_id):
    faq = FAQ.query.get_or_404(faq_id)
    
    if request.method == 'POST':
        faq.question = request.form.get('question')
        faq.answer = request.form.get('answer')
        faq.category = request.form.get('category')
        faq.is_pinned = 'is_pinned' in request.form
        
        db.session.commit()
        flash('FAQ updated successfully!', 'success')
        return redirect(url_for('admin.admin_faq'))
    
    return render_template('admin/faq_form.html', faq=faq)

@admin_bp.route('/faq/delete/<int:faq_id>')
@admin_required
def admin_faq_delete(faq_id):
    faq = FAQ.query.get_or_404(faq_id)
    db.session.delete(faq)
    db.session.commit()
    flash('FAQ deleted successfully!', 'success')
    return redirect(url_for('admin.admin_faq'))

# ===== ADMIN SUPPORT TICKETING =====
@admin_bp.route('/support')
@admin_required
def admin_support():
    status_filter = request.args.get('status', 'all')
    
    query = SupportTicket.query
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    tickets = query.order_by(SupportTicket.updated_at.desc()).all()
    
    stats = {
        'open': SupportTicket.query.filter_by(status='open').count(),
        'in_progress': SupportTicket.query.filter_by(status='in_progress').count(),
        'resolved': SupportTicket.query.filter_by(status='resolved').count(),
        'closed': SupportTicket.query.filter_by(status='closed').count()
    }
    
    return render_template('admin/support_dashboard.html', 
                         tickets=tickets, 
                         stats=stats, 
                         status_filter=status_filter)

@admin_bp.route('/support/ticket/<string:ticket_number>')
@admin_required
def admin_ticket_detail(ticket_number):
    ticket = SupportTicket.query.filter_by(ticket_number=ticket_number).first_or_404()
    
    ticket.last_admin_read_at = datetime.now(timezone.utc)
    db.session.commit()
    
    messages = ticket.messages.order_by(TicketMessage.created_at.asc()).all()
    
    return render_template('admin/ticket_detail.html', ticket=ticket, messages=messages)

def admin_compress_and_save_attachment(attachment, ticket_number, prefix=""):
    import os, time
    from werkzeug.utils import secure_filename
    
    ext = attachment.filename.rsplit('.', 1)[1].lower() if '.' in attachment.filename else ''
    if ext not in {'png', 'jpg', 'jpeg', 'pdf'}:
        return None
        
    upload_dir = os.path.join('static', 'uploads', 'tickets')
    os.makedirs(upload_dir, exist_ok=True)
    
    if ext in {'png', 'jpg', 'jpeg'}:
        from PIL import Image
        filename = secure_filename(f"{prefix}{ticket_number}_{int(time.time())}.jpg")
        target_path = os.path.join(upload_dir, filename)
        
        img = Image.open(attachment)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        max_width = 1200
        if img.width > max_width:
            ratio = max_width / float(img.width)
            height = int(float(img.height) * ratio)
            img = img.resize((max_width, height), Image.Resampling.LANCZOS)
        
        img.save(target_path, "JPEG", quality=65, optimize=True)
        return f"uploads/tickets/{filename}"
    elif ext == 'pdf':
        filename = secure_filename(f"{prefix}{ticket_number}_{int(time.time())}_{attachment.filename}")
        target_path = os.path.join(upload_dir, filename)
        attachment.save(target_path)
        return f"uploads/tickets/{filename}"
    return None

@admin_bp.route('/support/ticket/<string:ticket_number>/reply', methods=['POST'])
@admin_required
def admin_ticket_reply(ticket_number):
    admin_user = User.query.get(session['user_id'])
    ticket = SupportTicket.query.filter_by(ticket_number=ticket_number).first_or_404()
    
    message_text = request.form.get('message')
    attachment = request.files.get('attachment')
    
    if not message_text and not attachment:
        flash('Message cannot be empty.', 'error')
        return redirect(url_for('admin.admin_ticket_detail', ticket_number=ticket_number))
    
    attachment_url = None
    if attachment and attachment.filename != '':
        attachment_url = admin_compress_and_save_attachment(attachment, ticket_number, prefix="admin_reply_")
    
    message = TicketMessage(
        ticket_id=ticket.id,
        sender_id=admin_user.id,
        message=message_text or "Sent an attachment",
        is_admin_reply=True,
        attachment_url=attachment_url
    )
    
    if ticket.status == 'open':
        ticket.status = 'in_progress'
    
    ticket.updated_at = datetime.now(timezone.utc)
    ticket.last_reply_at = datetime.now(timezone.utc)
    
    db.session.add(message)
    db.session.commit()
    
    flash('Reply sent successfully!', 'success')
    return redirect(url_for('admin.admin_ticket_detail', ticket_number=ticket_number))

@admin_bp.route('/support/ticket/<string:ticket_number>/status', methods=['POST'])
@admin_required
def admin_ticket_status(ticket_number):
    ticket = SupportTicket.query.filter_by(ticket_number=ticket_number).first_or_404()
    new_status = request.form.get('status')
    
    if new_status in ['open', 'in_progress', 'resolved', 'closed']:
        ticket.status = new_status
        if new_status == 'resolved':
            ticket.resolved_at = datetime.now(timezone.utc)
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(f'Ticket status updated to {new_status}.', 'success')
    
    return redirect(url_for('admin.admin_ticket_detail', ticket_number=ticket_number))

@admin_bp.route('/support/ticket/<string:ticket_number>/note', methods=['POST'])
@admin_required
def admin_ticket_note(ticket_number):
    ticket = SupportTicket.query.filter_by(ticket_number=ticket_number).first_or_404()
    ticket.admin_note = request.form.get('admin_note', '')
    db.session.commit()
    flash('Admin note updated.', 'success')
    return redirect(url_for('admin.admin_ticket_detail', ticket_number=ticket_number))

@admin_bp.route('/user/<int:user_id>/reset-password', methods=['POST'])
def admin_reset_user_password(user_id):
    from models import User
    import secrets, string
    user = User.query.get_or_404(user_id)
    new_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    user.password = generate_password_hash(new_password)
    db.session.commit()
    flash(f'Password reset to: {new_password}', 'success')
    return redirect(url_for('admin.admin_user_detail', user_id=user_id))

@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.admin_users'))


# ===== ANALYTICS ROUTES =====

@admin_bp.route('/analytics')
@admin_required
def admin_analytics():
    """Admin analytics dashboard"""
    return render_template('admin/admin_analytics.html')


# ─── NEW: Admin User-Specific Analytics ───────────────────────────────

@admin_bp.route('/user/<int:user_id>/analytics')
@admin_required
def admin_user_analytics(user_id):
    """Admin view of a specific user's analytics dashboard"""
    user = User.query.get_or_404(user_id)
    return render_template('admin/admin_user_analytics.html', 
                          user_id=user_id, 
                          user_name=user.get_full_name())


@admin_bp.route('/api/user/<int:user_id>/challenges/metrics')
@admin_required
def api_user_challenges_metrics(user_id):
    """Get all active challenges with metrics for a specific user"""
    challenges = ChallengePurchase.query.filter_by(user_id=user_id).filter(
        ChallengePurchase.status.in_(['active', 'funded', 'flagged', 'under_review'])
    ).all()
    
    result = []
    for ch in challenges:
        result.append({
            'id': ch.id,
            'user_id': ch.user_id,
            'challenge_name': ch.challenge_template.name if ch.challenge_template else 'Challenge',
            'status': ch.status,
            'current_phase': ch.current_phase,
            'profit_percent': ch.profit_percent or 0,
            'daily_drawdown': ch.daily_drawdown or 0,
            'overall_drawdown': ch.overall_drawdown or 0,
            'risk_score': ch.risk_score or 0,
            'trading_days': ch.trading_days or 0,
            'days_remaining': ch.days_remaining or 0,
            'current_balance': ch.current_balance or 0,
            'current_equity': ch.current_equity or 0,
            'min_trading_days': ch.challenge_template.phase1_min_days if ch.challenge_template else 5,
            'completed_at': ch.completed_at.isoformat() if ch.completed_at else None
        })
    
    return jsonify({'success': True, 'challenges': result})


@admin_bp.route('/api/user/<int:user_id>/calendar')
@admin_required
def api_user_calendar(user_id):
    """Get calendar data for a specific user by month"""
    from models import Trade
    
    month_str = request.args.get('month', '')
    if not month_str:
        now = datetime.now(timezone.utc)
        month_str = f"{now.year}-{now.month:02d}"
    
    try:
        year, month = map(int, month_str.split('-'))
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid month format'}), 400
    
    # Get all challenges for this user
    user_challenges = ChallengePurchase.query.filter_by(user_id=user_id).all()
    challenge_ids = [ch.id for ch in user_challenges]
    
    if not challenge_ids:
        return jsonify({
            'success': True,
            'days': {},
            'summary': {
                'total_trades': 0,
                'total_profit': 0,
                'win_rate': 0,
                'win_streak': 0,
                'best_trade': None,
                'top_symbol': None
            }
        })
    
    # Get trades for this month across all user's challenges
    start_date = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    
    trades = Trade.query.filter(
        Trade.challenge_id.in_(challenge_ids),
        Trade.close_time >= start_date,
        Trade.close_time < end_date
    ).order_by(Trade.close_time.asc()).all()
    
    # Group trades by day
    days_data = {}
    all_profits = []
    symbol_counts = {}
    
    for trade in trades:
        if not trade.close_time:
            continue
            
        day_key = trade.close_time.strftime('%Y-%m-%d')
        if day_key not in days_data:
            days_data[day_key] = {
                'total_profit': 0,
                'total_trades': 0,
                'winning_trades': 0,
                'trades': []
            }
        
        profit = trade.profit or 0
        days_data[day_key]['total_profit'] += profit
        days_data[day_key]['total_trades'] += 1
        if profit > 0:
            days_data[day_key]['winning_trades'] += 1
        
        all_profits.append(profit)
        
        # Track symbols
        symbol = trade.symbol or 'Unknown'
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        
        # Get challenge name
        challenge = next((c for c in user_challenges if c.id == trade.challenge_id), None)
        
        days_data[day_key]['trades'].append({
            'id': trade.id,
            'symbol': trade.symbol or 'Unknown',
            'profit': profit,
            'lots': getattr(trade, 'lots', 0) or 0,
            'open_time': trade.open_time.isoformat() if trade.open_time else None,
            'close_time': trade.close_time.isoformat() if trade.close_time else None,
            'challenge_name': challenge.challenge_template.name if challenge and challenge.challenge_template else 'Challenge'
        })
    
    # Calculate summary
    total_trades = len(trades)
    total_profit = sum(all_profits)
    winning_trades = sum(1 for p in all_profits if p > 0)
    win_rate = round((winning_trades / total_trades * 100) if total_trades > 0 else 0, 1)
    
    # Best trade
    best_trade = max(trades, key=lambda t: t.profit or 0) if trades else None
    best_trade_data = None
    if best_trade:
        best_trade_data = {
            'profit': best_trade.profit or 0,
            'symbol': best_trade.symbol or 'Unknown'
        }
    
    # Top symbol
    top_symbol = max(symbol_counts, key=symbol_counts.get) if symbol_counts else None
    
    # Win streak
    win_streak = 0
    current_streak = 0
    for profit in all_profits:
        if profit > 0:
            current_streak += 1
            win_streak = max(win_streak, current_streak)
        else:
            current_streak = 0
    
    return jsonify({
        'success': True,
        'days': days_data,
        'summary': {
            'total_trades': total_trades,
            'total_profit': round(total_profit, 2),
            'win_rate': win_rate,
            'win_streak': win_streak,
            'best_trade': best_trade_data,
            'top_symbol': top_symbol
        }
    })

# ─── END NEW ROUTES ───────────────────────────────────────────────────


@admin_bp.route('/api/challenges/all')
@admin_required
def api_all_challenges():
    """API endpoint for all challenges with metrics"""
    from models import ChallengePurchase, User, ChallengeTemplate
    
    challenges = ChallengePurchase.query.all()
    
    result = []
    for ch in challenges:
        result.append({
            'id': ch.id,
            'user_id': ch.user_id,
            'user_name': ch.user_obj.get_full_name() if ch.user_obj else 'Unknown',
            'user_email': ch.user_obj.email if ch.user_obj else 'Unknown',
            'challenge_name': ch.challenge_template.name if ch.challenge_template else 'Challenge',
            'status': ch.status,
            'current_phase': ch.current_phase,
            'profit_percent': ch.profit_percent,
            'daily_drawdown': ch.daily_drawdown,
            'overall_drawdown': ch.overall_drawdown,
            'risk_score': ch.risk_score,
            'trading_days': ch.trading_days,
            'days_remaining': ch.days_remaining,
            'current_balance': ch.current_balance,
            'current_equity': ch.current_equity,
            'completed_at': ch.completed_at.isoformat() if ch.completed_at else None,
            'violation_reason': ch.violation_reason,
            'violation_timestamp': ch.violation_timestamp.isoformat() if ch.violation_timestamp else None,
        })
    
    return jsonify({'success': True, 'challenges': result})

@admin_bp.route('/api/challenge/<int:challenge_id>/details')
@admin_required
def api_challenge_details(challenge_id):
    from models import ChallengePurchase, RuleLog, ViolationEvidence

    ch = ChallengePurchase.query.get_or_404(challenge_id)

    violations = RuleLog.query.filter_by(
        challenge_id=challenge_id
    ).order_by(RuleLog.created_at.desc()).limit(20).all()

    violations_data = [{
        'rule_name': v.rule_name,
        'severity': v.severity,
        'message': v.message,
        'current_value': v.current_value,
        'threshold_value': v.threshold_value,
        'triggered_at': v.created_at.isoformat() if v.created_at else None
    } for v in violations]

    # Fetch all evidence records for this challenge
    evidences = ViolationEvidence.query.filter_by(
        challenge_purchase_id=challenge_id
    ).order_by(ViolationEvidence.created_at.desc()).all()

    evidence_data = [{
        'id': e.id,
        'violation_type': e.violation_type,
        'rule_name': e.rule_name,
        'rule_limit': e.rule_limit,
        'actual_value': e.actual_value,
        'drawdown_model': e.drawdown_model,
        'day_start_value': e.day_start_value,
        'lowest_value': e.lowest_value,
        'current_value': e.current_value,
        'balance': e.balance,
        'equity': e.equity,
        'floating_pnl': e.floating_pnl,
        'profit_percent': e.profit_percent,
        'daily_drawdown': e.daily_drawdown,
        'overall_drawdown': e.overall_drawdown,
        'trading_days': e.trading_days,
        'reason': e.reason,
        'severity': e.severity,
        'open_positions': e.open_positions_snapshot or [],
        'recent_trades': e.recent_trades_snapshot or [],
        'account_snapshot': e.account_snapshot_data or {},
        'is_reviewed': e.is_reviewed,
        'review_decision': e.review_decision,
        'review_notes': e.review_notes,
        'violation_timestamp': e.violation_timestamp.isoformat() if e.violation_timestamp else None,
        'created_at': e.created_at.isoformat() if e.created_at else None
    } for e in evidences]

    # 🎯 GET REAL TEMPLATE RULES FROM DATABASE
    template = ch.challenge_template
    template_rules = None
    
    if template:
        template_rules = {
            'challenge_type': template.challenge_type or 'one_phase',
            'account_size': template.account_size or 10000,
            'phase': template.phase or 1,
            
            # Phase 1 Rules
            'phase1_target': template.phase1_target,
            'phase1_daily_loss': template.phase1_daily_loss,
            'phase1_daily_dd_type': template.phase1_daily_dd_type or 'equity',
            'phase1_overall_loss': template.phase1_overall_loss,
            'phase1_overall_dd_type': template.phase1_overall_dd_type or 'equity',
            'phase1_min_days': template.phase1_min_days,
            'phase1_duration': template.phase1_duration,
            'phase1_leverage': template.phase1_leverage or '1:100',
            'phase1_rules': template.phase1_rules or '',
            
            # Phase 2 Rules
            'phase2_target': template.phase2_target,
            'phase2_daily_loss': template.phase2_daily_loss,
            'phase2_daily_dd_type': template.phase2_daily_dd_type or 'equity',
            'phase2_overall_loss': template.phase2_overall_loss,
            'phase2_overall_dd_type': template.phase2_overall_dd_type or 'equity',
            'phase2_min_days': template.phase2_min_days,
            'phase2_duration': template.phase2_duration,
            'phase2_leverage': template.phase2_leverage or '1:100',
            'phase2_rules': template.phase2_rules or '',
            
            # Instant Rules
            'instant_daily_loss': template.instant_daily_loss,
            'instant_daily_dd_type': template.instant_daily_dd_type or 'equity',
            'instant_overall_loss': template.instant_overall_loss,
            'instant_overall_dd_type': template.instant_overall_dd_type or 'equity',
            'instant_min_days': template.instant_min_days,
            'instant_leverage': template.instant_leverage or '1:100',
            'instant_rules': template.instant_rules or '',
            
            # General Settings
            'user_profit_share': template.user_profit_share or 80,
            'payout_cycle': template.payout_cycle or 'biweekly',
            'weekend_trading': template.weekend_trading if template.weekend_trading is not None else True,
            'is_active': template.is_active if template.is_active is not None else True,
            'description': template.description or '',
            
            # 🛡️ Safety Rules
            'sl_mandatory_enabled': template.sl_mandatory_enabled if template.sl_mandatory_enabled is not None else False,
            'sl_grace_period_minutes': template.sl_grace_period_minutes or 3,
            'max_risk_per_trade_percent': template.max_risk_per_trade_percent or 1.5,
            'activity_rule_enabled': template.activity_rule_enabled if template.activity_rule_enabled is not None else False,
            'max_inactive_days': template.max_inactive_days or 4,
        }
    
    # Determine current phase rules
    ctype = ch.challenge_type or 'one_phase'
    phase = ch.current_phase or 1
    
    if ctype == 'instant':
        current_rules = {
            'phase_name': 'Instant Funded',
            'target': template.instant_daily_loss,  # No profit target for instant
            'daily_loss': template.instant_daily_loss,
            'daily_dd_type': template.instant_daily_dd_type or 'equity',
            'overall_loss': template.instant_overall_loss,
            'overall_dd_type': template.instant_overall_dd_type or 'equity',
            'min_days': template.instant_min_days or 0,
            'duration': 365,
            'leverage': template.instant_leverage or '1:100',
        } if template else None
    elif ctype == 'two_phase' and phase == 2:
        current_rules = {
            'phase_name': 'Phase 2',
            'target': template.phase2_target,
            'daily_loss': template.phase2_daily_loss,
            'daily_dd_type': template.phase2_daily_dd_type or 'equity',
            'overall_loss': template.phase2_overall_loss,
            'overall_dd_type': template.phase2_overall_dd_type or 'equity',
            'min_days': template.phase2_min_days or 0,
            'duration': template.phase2_duration or 60,
            'leverage': template.phase2_leverage or '1:100',
        } if template else None
    else:
        current_rules = {
            'phase_name': 'Phase 1',
            'target': template.phase1_target,
            'daily_loss': template.phase1_daily_loss,
            'daily_dd_type': template.phase1_daily_dd_type or 'equity',
            'overall_loss': template.phase1_overall_loss,
            'overall_dd_type': template.phase1_overall_dd_type or 'equity',
            'min_days': template.phase1_min_days or 0,
            'duration': template.phase1_duration or 30,
            'leverage': template.phase1_leverage or '1:100',
        } if template else None

    return jsonify({
        'success': True,
        'challenge': {
            'id': ch.id,
            'user_name': ch.user_obj.get_full_name() if ch.user_obj else 'Unknown',
            'user_email': ch.user_obj.email if ch.user_obj else 'Unknown',
            'challenge_name': ch.challenge_template.name if ch.challenge_template else 'Challenge',
            'status': ch.status,
            'monitoring_status': ch.monitoring_status,
            'current_phase': ch.current_phase,
            'challenge_type': ctype,
            'profit_percent': ch.profit_percent,
            'daily_drawdown': ch.daily_drawdown,
            'overall_drawdown': ch.overall_drawdown,
            'risk_score': ch.risk_score,
            'trading_days': ch.trading_days,
            'days_remaining': ch.days_remaining,
            'current_balance': ch.current_balance,
            'current_equity': ch.current_equity,
            'min_trading_days': ch.challenge_template.phase1_min_days if ch.challenge_template else 5,
            'violation_reason': ch.violation_reason,
            'violation_timestamp': ch.violation_timestamp.isoformat() if ch.violation_timestamp else None,
            'review_required': ch.review_required,
            'violations': violations_data,
            'evidence': evidence_data,
            # 🎯 REAL TEMPLATE RULES
            'template_rules': template_rules,
            # 🎯 CURRENT PHASE RULES (for analytics)
            'current_rules': current_rules,
        }
    })

@admin_bp.route('/api/challenge/<int:challenge_id>/violations')
@admin_required
def api_challenge_violations(challenge_id):
    """Get all violations for a challenge (separate endpoint)"""
    from models import RuleLog
    
    violations = RuleLog.query.filter_by(
        challenge_id=challenge_id
    ).order_by(RuleLog.created_at.desc()).all()
    
    return jsonify({
        'success': True,
        'violations': [{
            'id': v.id,
            'rule_name': v.rule_name,
            'severity': v.severity,
            'message': v.message,
            'current_value': v.current_value,
            'threshold_value': v.threshold_value,
            'created_at': v.created_at.isoformat() if v.created_at else None
        } for v in violations]
    })

@admin_bp.route('/api/challenge/<int:challenge_id>/clear-flag', methods=['POST'])
@admin_required
def api_clear_flag(challenge_id):
    """Clear flagged status (admin review cleared)"""
    from models import ChallengePurchase
    
    challenge = ChallengePurchase.query.get_or_404(challenge_id)
    
    challenge.monitoring_status = 'active'
    challenge.review_required = False
    challenge.status = 'active'
    challenge.violation_reason = None
        
    challenge.manipulation_check_baseline = challenge.current_balance
    challenge.manipulation_baseline_set_at = datetime.now(timezone.utc)
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Flag cleared, challenge is active again'})

@admin_bp.route('/api/challenge/action', methods=['POST'])
@admin_required
def api_challenge_action():
    """Force actions on challenges"""
    from models import ChallengePurchase
    from datetime import datetime, timedelta, timezone
    
    data = request.get_json()
    challenge_id = data.get('challenge_id')
    action = data.get('action')
    
    ch = ChallengePurchase.query.get_or_404(challenge_id)
    
    if action == 'review':
        ch.monitoring_status = 'under_review'
        ch.review_required = True
        ch.status = 'under_review'
        
    elif action == 'clear':
        # CLEAR FLAG - User can continue trading, flag removed
        ch.monitoring_status = 'active'
        ch.review_required = False
        ch.status = 'active'
        ch.violation_reason = None
        ch.risk_score = 0  # Reset risk score after clearing
        ch.manipulation_check_baseline = ch.current_balance
        ch.manipulation_baseline_set_at = datetime.now(timezone.utc)
        log_rule(ch.id, "admin_clear_flag", "info", "Admin cleared the flag. Account is active again.")
        
    elif action == 'extend':
        if ch.end_date:
            ch.end_date += timedelta(days=7)
            ch.days_remaining = (ch.end_date - datetime.now(timezone.utc)).days
            log_rule(ch.id, "admin_extend", "info", f"Admin extended challenge by 7 days")
            
    elif action == 'fail':
        ch.status = 'failed'
        ch.is_terminated = True
        ch.monitoring_status = 'failed'
        ch.review_required = False
        ch.completed_at = datetime.now(timezone.utc)
        log_rule(ch.id, "admin_fail", "critical", "Admin force failed the challenge")
        _notify_challenge_breached(ch, session.get('user_id'))
        
    elif action == 'pass':
        ch.status = 'passed'
        ch.completed_at = datetime.now(timezone.utc)
        ch.monitoring_status = 'passed'
        ch.review_required = False
        ch.pass_reason = "Admin force passed the challenge"
        log_rule(ch.id, "admin_pass", "success", "Admin force passed the challenge")
        _notify_challenge_passed(ch, session.get('user_id'))
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Action {action} completed'})

# Helper function for logging admin actions
def log_rule(challenge_id, rule_name, severity, message, current_value=None, threshold_value=None):
    """Helper to log rule events from admin actions"""
    from models import RuleLog
    try:
        log = RuleLog(
            challenge_id=challenge_id,
            rule_name=rule_name,
            severity=severity,
            message=message[:500],
            current_value=current_value,
            threshold_value=threshold_value,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"Failed to log admin action: {e}")

@admin_bp.route('/partner/<int:partner_id>/ban', methods=['POST'])
@admin_required
def ban_partner(partner_id):
    partner = User.query.get_or_404(partner_id)
    if partner.role != 'partner':
        flash('User is not a partner', 'error')
        return redirect(url_for('admin.partners'))
        
    partner.is_banned = True
    
    log = AdminLog(
        admin_id=session['user_id'],
        action='ban_partner',
        target_type='partner',
        target_id=partner.id,
        details=f'Partner {partner.email} banned',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Partner {partner.email} banned', 'success')
    return redirect(url_for('admin.partners'))

@admin_bp.route('/partner/<int:partner_id>/unban', methods=['POST'])
@admin_required
def unban_partner(partner_id):
    partner = User.query.get_or_404(partner_id)
    if partner.role != 'partner':
        flash('User is not a partner', 'error')
        return redirect(url_for('admin.partners'))
        
    partner.is_banned = False
    
    log = AdminLog(
        admin_id=session['user_id'],
        action='unban_partner',
        target_type='partner',
        target_id=partner.id,
        details=f'Partner {partner.email} unbanned',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Access restored for {partner.email}', 'success')
    return redirect(url_for('admin.partners'))

@admin_bp.route('/partner/<int:partner_id>/revoke', methods=['POST'])
@admin_required
def revoke_partner(partner_id):
    partner = User.query.get_or_404(partner_id)
    if partner.role != 'partner':
        flash('User is not a partner', 'error')
        return redirect(url_for('admin.partners'))
        
    partner.role = 'user'
    partner.is_banned = True
    
    log = AdminLog(
        admin_id=session['user_id'],
        action='revoke_partner',
        target_type='partner',
        target_id=partner.id,
        details=f'Partner access fully revoked for {partner.email}',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Partner access fully revoked for {partner.email}', 'success')
    return redirect(url_for('admin.partners'))

@admin_bp.route('/partners')
@admin_required
def partners():
    from models import PartnerEarnings
    from sqlalchemy import func
    
    # Get all partners
    all_partners = User.query.filter_by(role='partner').all()
    
    # Get earnings for each partner
    partner_stats = {}
    for p in all_partners:
        total_earned = db.session.query(func.sum(PartnerEarnings.partner_share)).filter_by(partner_id=p.id).scalar() or 0.0
        sales_count = PartnerEarnings.query.filter_by(partner_id=p.id).count()
        partner_stats[p.id] = {
            'total_earned': total_earned,
            'sales_count': sales_count
        }
        
    return render_template('admin/partners.html', partners=all_partners, stats=partner_stats)

@admin_bp.route('/partner/create', methods=['POST'])
@admin_required
def create_partner():
    from werkzeug.security import generate_password_hash
    from models import AdminLog
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not all([first_name, last_name, email, password]):
        flash('All fields are required', 'error')
        return redirect(url_for('admin.partners'))
        
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash('Email already registered', 'error')
        return redirect(url_for('admin.partners'))
        
    new_partner = User(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone='',
        dob=datetime.now(timezone.utc).date(),
        country='N/A',
        password=generate_password_hash(password),
        role='partner',
        is_admin=False
    )
    db.session.add(new_partner)
    
    log = AdminLog(
        admin_id=session['user_id'],
        action='create_partner',
        target_type='partner',
        target_id=0,
        details=f'Created new partner {email}',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Partner {email} created successfully', 'success')
    return redirect(url_for('admin.partners'))

@admin_bp.route('/partner/<int:partner_id>/earnings')
@admin_required
def partner_earnings(partner_id):
    from models import PartnerEarnings
    partner = User.query.get_or_404(partner_id)
    if partner.role != 'partner':
        flash('User is not a partner', 'error')
        return redirect(url_for('admin.partners'))
        
    earnings = PartnerEarnings.query.filter_by(partner_id=partner.id).order_by(PartnerEarnings.purchased_at.desc()).all()
    
    return render_template('admin/partner_earnings.html', partner=partner, earnings=earnings)

@admin_bp.route('/partner-earning/<int:earning_id>/toggle-hide', methods=['POST'])
@admin_required
def toggle_hide_earning(earning_id):
    from models import PartnerEarnings, AdminLog
    earning = PartnerEarnings.query.get_or_404(earning_id)
    earning.is_hidden = not earning.is_hidden
    
    log = AdminLog(
        admin_id=session['user_id'],
        action='toggle_hide_earning',
        target_type='partner_earning',
        target_id=earning.id,
        details=f'Toggled hide state for earning {earning.id} to {earning.is_hidden}',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Earning visibility updated successfully', 'success')
    return redirect(url_for('admin.partner_earnings', partner_id=earning.partner_id))

@admin_bp.route('/notifications', methods=['GET', 'POST'])
@admin_required
def admin_notifications():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        target_type = request.form.get('target_type', 'global')
        target_email = request.form.get('target_email', '').strip()
        expiry_type = request.form.get('expiry_type', 'none')
        expiry_days = request.form.get('expiry_days', '').strip()
        template_id = request.form.get('template_id', '').strip()

        if not title or not message:
            flash('Title and message are required.', 'error')
            return redirect(url_for('admin.admin_notifications'))

        target_user = None
        if target_type == 'specific':
            if not target_email:
                flash('Target user email is required for specific notifications.', 'error')
                return redirect(url_for('admin.admin_notifications'))
            target_user = User.query.filter_by(email=target_email).first()
            if not target_user:
                flash(f'User with email {target_email} not found.', 'error')
                return redirect(url_for('admin.admin_notifications'))

        # Calculate expiration date
        expires_at = None
        now_utc = datetime.now(timezone.utc)
        if expiry_type == '7':
            expires_at = now_utc + timedelta(days=7)
        elif expiry_type == '15':
            expires_at = now_utc + timedelta(days=15)
        elif expiry_type == '30':
            expires_at = now_utc + timedelta(days=30)
        elif expiry_type == '60':
            expires_at = now_utc + timedelta(days=60)
        elif expiry_type == 'custom':
            try:
                days = int(expiry_days)
                if days <= 0:
                    raise ValueError()
                expires_at = now_utc + timedelta(days=days)
            except ValueError:
                flash('Please enter a valid positive number of days for custom expiry.', 'error')
                return redirect(url_for('admin.admin_notifications'))

        try:
            notification = Notification(
                title=title,
                message=message,
                is_global=(target_type == 'global'),
                target_user_id=target_user.id if target_user else None,
                created_by_admin_id=session['user_id'],
                expires_at=expires_at,
                is_deleted=False
            )
            db.session.add(notification)
            db.session.flush()

            # Increment template use count if a template was used
            if template_id:
                template = NotificationTemplate.query.get(int(template_id))
                if template:
                    template.increment_use_count()

            if not notification.is_global and target_user:
                user_notif = UserNotification(
                    notification_id=notification.id,
                    user_id=target_user.id,
                    is_read=False
                )
                db.session.add(user_notif)

            # Log admin action
            log = AdminLog(
                admin_id=session['user_id'],
                action='create_notification',
                target_type='notification',
                target_id=notification.id,
                details=f'Created {"global" if notification.is_global else f"targeted (user_id={target_user.id})"} notification: "{title}"',
                ip_address=request.remote_addr
            )
            db.session.add(log)
            db.session.commit()

            flash('Notification sent successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            print(f"Error creating notification: {e}")
            flash('Error sending notification. Please try again.', 'error')

        return redirect(url_for('admin.admin_notifications'))

    # GET request - pass templates to the view
    templates = NotificationTemplate.query.filter_by(is_active=True).order_by(NotificationTemplate.name).all()
    notifications = Notification.query.filter_by(is_deleted=False).order_by(Notification.created_at.desc()).all()
    
    # Calculate read stats dynamically
    for n in notifications:
        n.read_count = UserNotification.query.filter_by(notification_id=n.id, is_read=True).count()
        if n.is_global:
            n.total_count = User.query.filter_by(is_admin=False, is_banned=False).count()
        else:
            n.total_count = 1

    return render_template('admin/notifications.html', 
                         notifications=notifications, 
                         templates=templates)

@admin_bp.route('/notifications/delete/<int:notification_id>', methods=['POST'])
@admin_required
def admin_delete_notification(notification_id):
    notification = Notification.query.filter_by(id=notification_id, is_deleted=False).first_or_404()
    notification.is_deleted = True

    log = AdminLog(
        admin_id=session['user_id'],
        action='delete_notification',
        target_type='notification',
        target_id=notification.id,
        details=f'Soft-deleted notification: "{notification.title}"',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()

    flash('Notification deleted successfully!', 'success')
    return redirect(url_for('admin.admin_notifications'))


@admin_bp.route('/coupons', methods=['GET', 'POST'])
@admin_required
def admin_coupons():
    if request.method == 'POST':
        try:
            code = request.form.get('code', '').upper().strip()
            description = request.form.get('description', '').strip()
            coupon_type = request.form.get('coupon_type', 'universal')
            discount_type = request.form.get('discount_type', 'percent')
            discount_value = float(request.form.get('discount_value', 0))
            max_uses = request.form.get('max_uses')
            max_uses = int(max_uses) if max_uses and max_uses.strip() else None
            expires_at_str = request.form.get('expires_at')
            
            expires_at = None
            if expires_at_str and expires_at_str.strip():
                expires_at = datetime.fromisoformat(expires_at_str)
            
            # Check duplicate code
            existing = Coupon.query.filter_by(code=code, is_deleted=False).first()
            if existing:
                flash(f'Coupon code "{code}" already exists.', 'error')
                return redirect(url_for('admin.admin_coupons'))

            coupon = Coupon(
                code=code,
                description=description,
                coupon_type=coupon_type,
                discount_type=discount_type,
                discount_value=discount_value,
                max_uses=max_uses,
                expires_at=expires_at,
                created_by_admin_id=session['user_id']
            )

            if coupon_type == 'influencer':
                influencer_email = request.form.get('influencer_email', '').strip()
                influencer = User.query.filter_by(email=influencer_email).first()
                if not influencer:
                    flash(f'Influencer user with email "{influencer_email}" not found.', 'error')
                    return redirect(url_for('admin.admin_coupons'))
                coupon.influencer_id = influencer.id

            db.session.add(coupon)
            db.session.flush() # get coupon ID

            if coupon_type == 'specific':
                assigned_emails = request.form.get('assigned_emails', '').strip()
                if assigned_emails:
                    email_list = [e.strip() for e in assigned_emails.split(',') if e.strip()]
                    invalid_emails = []
                    for email in email_list:
                        user = User.query.filter_by(email=email).first()
                        if user:
                            assignment = CouponAssignment(coupon_id=coupon.id, user_id=user.id)
                            db.session.add(assignment)
                            create_notification(
                                user.id,
                                'New Coupon Available',
                                'A new discount coupon has been added to your account. Use it on your next challenge purchase and save.',
                                'coupon',
                                action_url='/user/my-coupons',
                                icon='gift',
                                admin_id=session.get('user_id'),
                                dedupe_key=f'coupon-assigned:{coupon.id}:{user.id}',
                            )
                        else:
                            invalid_emails.append(email)
                    if invalid_emails:
                        flash(f"Coupon created, but these emails were not found: {', '.join(invalid_emails)}", 'warning')
            elif coupon_type == 'universal':
                notify_all_users(
                    'New Promotion Available',
                    'A new promotional coupon is now available. Visit the coupons section and claim your discount.',
                    'promotion',
                    action_url='/user/my-coupons',
                    icon='money',
                    admin_id=session.get('user_id'),
                    dedupe_key=f'global-coupon:{coupon.id}',
                )

            log = AdminLog(
                admin_id=session['user_id'],
                action='create_coupon',
                target_type='coupon',
                target_id=coupon.id,
                details=f'Created coupon: {code} ({coupon_type})',
                ip_address=request.remote_addr
            )
            db.session.add(log)
            db.session.commit()
            
            flash(f'Coupon "{code}" created successfully!', 'success')
            return redirect(url_for('admin.admin_coupons'))

        except Exception as e:
            db.session.rollback()
            print(f"Error creating coupon: {e}")
            flash('Error creating coupon. Please verify your input.', 'error')
            return redirect(url_for('admin.admin_coupons'))

    coupons = Coupon.query.filter_by(is_deleted=False).order_by(Coupon.created_at.desc()).all()
    return render_template('admin/coupons.html', coupons=coupons)


@admin_bp.route('/coupons/<int:coupon_id>')
@admin_required
def admin_coupon_detail(coupon_id):
    coupon = Coupon.query.filter_by(id=coupon_id, is_deleted=False).first_or_404()
    
    # Calculate stats
    usages = CouponUsage.query.filter_by(coupon_id=coupon.id).order_by(CouponUsage.used_at.desc()).all()
    
    total_discount_given = sum(u.discount_amount for u in usages)
    total_revenue_generated = sum(u.final_price for u in usages)
    
    return render_template('admin/coupon_detail.html', 
                           coupon=coupon, 
                           usages=usages,
                           total_discount_given=total_discount_given,
                           total_revenue_generated=total_revenue_generated)


@admin_bp.route('/coupons/<int:coupon_id>/delete', methods=['POST'])
@admin_required
def admin_delete_coupon(coupon_id):
    coupon = Coupon.query.filter_by(id=coupon_id, is_deleted=False).first_or_404()
    coupon.is_deleted = True
    coupon.is_active = False
    
    log = AdminLog(
        admin_id=session['user_id'],
        action='delete_coupon',
        target_type='coupon',
        target_id=coupon.id,
        details=f'Soft-deleted coupon: {coupon.code}',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Coupon "{coupon.code}" deleted successfully!', 'success')
    return redirect(url_for('admin.admin_coupons'))


@admin_bp.route('/coupons/analytics')
@admin_required
def admin_coupon_analytics():
    # Gather analytics
    total_coupons = Coupon.query.filter_by(is_deleted=False).count()
    active_coupons = Coupon.query.filter_by(is_deleted=False, is_active=True).count()
    
    now = datetime.now(timezone.utc)
    expired_coupons = Coupon.query.filter(
        Coupon.is_deleted == False,
        Coupon.expires_at != None,
        Coupon.expires_at < now
    ).count()
    
    usages = CouponUsage.query.order_by(CouponUsage.used_at.asc()).all()
    total_usages = len(usages)
    
    total_discount_given = sum(u.discount_amount for u in usages)
    total_revenue_generated = sum(u.final_price for u in usages)
    
    # Top performing coupons by usage count
    top_coupons = db.session.query(
        Coupon.code,
        Coupon.coupon_type,
        db.func.count(CouponUsage.id).label('usage_count'),
        db.func.sum(CouponUsage.final_price).label('revenue')
    ).join(CouponUsage, CouponUsage.coupon_id == Coupon.id)\
     .filter(Coupon.is_deleted == False)\
     .group_by(Coupon.id)\
     .order_by(db.desc('usage_count'))\
     .limit(5).all()

    # Timeline data for last 30 days
    thirty_days_ago = now - timedelta(days=30)
    timeline_usages = db.session.query(
        db.func.date(CouponUsage.used_at).label('date'),
        db.func.count(CouponUsage.id).label('count')
    ).filter(CouponUsage.used_at >= thirty_days_ago)\
     .group_by(db.func.date(CouponUsage.used_at))\
     .order_by('date').all()
     
    timeline_labels = [str(t.date) for t in timeline_usages]
    timeline_values = [int(t.count) for t in timeline_usages]
    
    return render_template('admin/coupon_analytics.html',
                           total_coupons=total_coupons,
                           active_coupons=active_coupons,
                           expired_coupons=expired_coupons,
                           total_usages=total_usages,
                           total_discount_given=total_discount_given,
                           total_revenue_generated=total_revenue_generated,
                           top_coupons=top_coupons,
                           timeline_labels=timeline_labels,
                           timeline_values=timeline_values)



# Add this at the top of admin_routes.py with other imports
from sqlalchemy import func, extract, and_, or_
from models import (
    db, User, ChallengeTemplate, ChallengePurchase, Payout, FAQ, 
    SupportTicket, TicketMessage, Payment, AdminLog, Notification, 
    UserNotification, NotificationTemplate, Coupon, CouponUsage, 
    CouponAssignment, PartnerEarnings, RuleLog
)

@admin_bp.route('/palantir')
@admin_required
def admin_palantir():
    """Palantir Command Center"""
    return render_template('admin/palantir.html')

@admin_bp.route('/api/palantir')
@admin_required
def api_palantir():
    """API for Palantir - all dashboard data"""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)
    
    # ===== USERS =====
    total_users = User.query.count()
    users_today = User.query.filter(User.created_at >= today_start).count()
    users_this_month = User.query.filter(
        extract('month', User.created_at) == now.month,
        extract('year', User.created_at) == now.year
    ).count()
    
    # User growth percentages
    yesterday_start = today_start - timedelta(days=1)
    users_yesterday = User.query.filter(
        User.created_at >= yesterday_start, 
        User.created_at < today_start
    ).count()
    growth_today = round((users_today / max(users_yesterday, 1)) * 100, 1) if users_yesterday > 0 else 100
    
    # Registrations by day (last 30 days)
    reg_by_day = db.session.query(
        func.date(User.created_at).label('date'),
        func.count(User.id).label('count')
    ).filter(User.created_at >= thirty_days_ago)\
     .group_by(func.date(User.created_at))\
     .order_by('date').all()
    
    reg_labels = [str(r.date) for r in reg_by_day]
    reg_values = [r.count for r in reg_by_day]
    
    # Latest 5 registrations
    latest_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    latest_registrations = [{
        'name': u.get_full_name(),
        'email': u.email,
        'country': u.country or 'N/A',
        'created_at': u.created_at.isoformat() if u.created_at else None
    } for u in latest_users]
    
    # ===== REVENUE =====
    def get_revenue(start=None, end=None):
        q = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
            Payment.status.in_(['SUCCESS', 'success'])
        )
        if start: q = q.filter(Payment.created_at >= start)
        if end: q = q.filter(Payment.created_at < end)
        return float(q.scalar() or 0)
    
    revenue_today = get_revenue(today_start)
    revenue_yesterday = get_revenue(today_start - timedelta(days=1), today_start)
    revenue_this_month = get_revenue(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    revenue_lifetime = get_revenue()
    
    # Revenue by day (last 30 days)
    rev_by_day = db.session.query(
        func.date(Payment.created_at).label('date'),
        func.coalesce(func.sum(Payment.amount), 0).label('total')
    ).filter(
        Payment.status.in_(['SUCCESS', 'success']),
        Payment.created_at >= thirty_days_ago
    ).group_by(func.date(Payment.created_at))\
     .order_by('date').all()
    
    rev_labels = [str(r.date) for r in rev_by_day]
    rev_values = [float(r.total) for r in rev_by_day]
    
    # ===== CHALLENGES =====
    active_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.status.in_(['active', 'funded']),
        ChallengePurchase.is_terminated == False
    ).count()
    
    funded_accounts = ChallengePurchase.query.filter(
        ChallengePurchase.status == 'funded'
    ).count()
    
    breached_accounts = ChallengePurchase.query.filter(
        ChallengePurchase.is_terminated == True
    ).count()
    
    # Challenge rankings
    challenge_rankings = db.session.query(
        ChallengeTemplate.name,
        ChallengeTemplate.price,
        func.count(ChallengePurchase.id).label('total_purchases'),
        func.coalesce(func.sum(Payment.amount), 0).label('revenue')
    ).join(ChallengePurchase, ChallengePurchase.challenge_template_id == ChallengeTemplate.id)\
     .join(Payment, Payment.challenge_purchase_id == ChallengePurchase.id)\
     .filter(Payment.status.in_(['SUCCESS', 'success']))\
     .group_by(ChallengeTemplate.id)\
     .order_by(func.count(ChallengePurchase.id).desc())\
     .all()
    
    rankings = [{
        'name': r.name,
        'price': float(r.price),
        'total_purchases': r.total_purchases,
        'revenue': float(r.revenue)
    } for r in challenge_rankings]
    
    top_challenge = rankings[0]['name'] if rankings else 'None'
    
    # ===== KYC =====
    pending_kyc = User.query.filter_by(kyc_status='submitted').count()
    approved_kyc = User.query.filter_by(kyc_status='approved').count()
    rejected_kyc = User.query.filter_by(kyc_status='rejected').count()
    kyc_today = User.query.filter(
        User.kyc_status == 'submitted',
        User.kyc_submitted_at >= today_start
    ).count()
    
    latest_kyc = User.query.filter(
        User.kyc_status.in_(['submitted', 'approved', 'rejected'])
    ).order_by(User.kyc_submitted_at.desc().nullslast()).limit(10).all()
    
    kyc_list = [{
        'user_id': u.id,
        'user_name': u.get_full_name(),
        'country': u.country or 'N/A',
        'status': u.kyc_status,
        'submitted_at': u.kyc_submitted_at.isoformat() if u.kyc_submitted_at else None
    } for u in latest_kyc]
    
    # ===== SUPPORT =====
    open_tickets = SupportTicket.query.filter_by(status='open').count()
    urgent_tickets = SupportTicket.query.filter(
        SupportTicket.status == 'open',
        SupportTicket.priority == 'urgent'
    ).count()
    closed_today = SupportTicket.query.filter(
        SupportTicket.status == 'closed',
        SupportTicket.resolved_at >= today_start
    ).count()
    
    latest_tickets = SupportTicket.query.order_by(
        SupportTicket.created_at.desc()
    ).limit(10).all()
    
    tickets_list = [{
        'ticket_number': t.ticket_number,
        'user_name': t.user.get_full_name() if t.user else 'Unknown',
        'subject': t.subject,
        'status': t.status,
        'created_at': t.created_at.isoformat() if t.created_at else None
    } for t in latest_tickets]
    
    # ===== PAYMENTS =====
    successful_payments = Payment.query.filter(Payment.status.in_(['SUCCESS', 'success'])).count()
    pending_payments_count = Payment.query.filter(Payment.status.ilike('pending')).count()
    failed_payments_count = Payment.query.filter(Payment.status.ilike('failed')).count()
    total_payments = successful_payments + pending_payments_count + failed_payments_count
    success_rate = round((successful_payments / max(total_payments, 1)) * 100, 1)
    
    latest_payments = Payment.query.order_by(Payment.created_at.desc()).limit(10).all()
    payments_list = [{
        'order_id': p.payment_id,
        'user_name': p.user.get_full_name() if p.user else 'Unknown',
        'amount': float(p.amount),
        'status': p.status,
        'created_at': p.created_at.isoformat() if p.created_at else None
    } for p in latest_payments]
    
    # ===== COUPONS =====
    active_coupons_count = Coupon.query.filter_by(is_active=True, is_deleted=False).count()
    expired_coupons_count = Coupon.query.filter_by(is_deleted=False).filter(
        Coupon.expires_at < now
    ).count()
    
    top_coupons = db.session.query(
        Coupon.code,
        func.count(CouponUsage.id).label('uses'),
        func.coalesce(func.sum(CouponUsage.final_price), 0).label('revenue')
    ).join(CouponUsage, CouponUsage.coupon_id == Coupon.id)\
     .filter(Coupon.is_deleted == False)\
     .group_by(Coupon.id)\
     .order_by(func.count(CouponUsage.id).desc())\
     .limit(10).all()
    
    coupons_list = [{
        'code': c.code,
        'uses': c.uses,
        'revenue': float(c.revenue)
    } for c in top_coupons]
    
    # ===== PARTNERS =====
    total_partners = User.query.filter_by(role='partner', is_banned=False).count()
    
    partner_rankings = db.session.query(
        User.first_name,
        User.last_name,
        func.count(PartnerEarnings.id).label('referrals'),
        func.coalesce(func.sum(PartnerEarnings.purchase_amount), 0).label('revenue'),
        func.coalesce(func.sum(PartnerEarnings.partner_share), 0).label('commission')
    ).join(PartnerEarnings, PartnerEarnings.partner_id == User.id)\
     .filter(User.role == 'partner')\
     .group_by(User.id)\
     .order_by(func.count(PartnerEarnings.id).desc())\
     .limit(5).all()
    
    partners_list = [{
        'name': f"{p.first_name} {p.last_name}",
        'referrals': p.referrals,
        'revenue': float(p.revenue),
        'commission': float(p.commission)
    } for p in partner_rankings]
    
    # ===== RISK =====
    near_daily_loss = ChallengePurchase.query.filter(
        ChallengePurchase.status.in_(['active', 'funded']),
        ChallengePurchase.is_terminated == False,
        ChallengePurchase.daily_drawdown >= 4.0  # 80% of typical 5% limit
    ).count()
    
    near_overall_loss = ChallengePurchase.query.filter(
        ChallengePurchase.status.in_(['active', 'funded']),
        ChallengePurchase.is_terminated == False,
        ChallengePurchase.overall_drawdown >= 8.0  # 80% of typical 10% limit
    ).count()
    
    require_review = ChallengePurchase.query.filter_by(review_required=True).count()
    
    breached_today = ChallengePurchase.query.filter(
        ChallengePurchase.is_terminated == True,
        ChallengePurchase.completed_at >= today_start
    ).count()
    
    # ===== SUMMARY =====
    summary = {
        'new_users_today': users_today,
        'revenue_today': revenue_today,
        'top_challenge': top_challenge,
        'pending_kyc': pending_kyc,
        'pending_tickets': open_tickets,
        'system_health': 'NORMAL'
    }
    
    # ===== ACTIONS =====
    actions = {
        'pending_kyc': pending_kyc,
        'open_tickets': open_tickets,
        'failed_payments': failed_payments_count,
        'near_breach': near_daily_loss + near_overall_loss,
        'require_review': require_review
    }
    
    return jsonify({
        'success': True,
        'summary': summary,
        'actions': actions,
        'users': {
            'total': total_users,
            'today': users_today,
            'this_month': users_this_month,
            'growth_today': growth_today,
            'registrations_by_day_labels': reg_labels,
            'registrations_by_day_values': reg_values,
            'latest': latest_registrations
        },
        'revenue': {
            'today': revenue_today,
            'yesterday': revenue_yesterday,
            'this_month': revenue_this_month,
            'lifetime': revenue_lifetime,
            'revenue_by_day_labels': rev_labels,
            'revenue_by_day_values': rev_values
        },
        'challenges': {
            'active': active_challenges,
            'funded': funded_accounts,
            'breached': breached_accounts,
            'rankings': rankings
        },
        'kyc': {
            'pending': pending_kyc,
            'approved': approved_kyc,
            'rejected': rejected_kyc,
            'today': kyc_today,
            'latest': kyc_list
        },
        'support': {
            'open': open_tickets,
            'urgent': urgent_tickets,
            'closed_today': closed_today,
            'latest': tickets_list
        },
        'payments': {
            'successful': successful_payments,
            'pending': pending_payments_count,
            'failed': failed_payments_count,
            'success_rate': success_rate,
            'latest': payments_list
        },
        'coupons': {
            'active': active_coupons_count,
            'expired': expired_coupons_count,
            'top_10': coupons_list
        },
        'partners': {
            'total': total_partners,
            'rankings': partners_list
        },
        'risk': {
            'near_daily_loss': near_daily_loss,
            'near_overall_loss': near_overall_loss,
            'require_review': require_review,
            'breached_today': breached_today,
            'funded_accounts': funded_accounts
        }
    })

@admin_bp.route('/api/palantir/activity')
@admin_required
def api_palantir_activity():
    """Activity feed for Palantir - last 50 events"""
    events = []
    
    # Latest 10 registrations
    users = User.query.order_by(User.created_at.desc()).limit(10).all()
    for u in users:
        events.append({
            'timestamp': u.created_at.isoformat() if u.created_at else None,
            'type': 'registration',
            'user': u.get_full_name(),
            'description': f"New registration from {u.country or 'Unknown'}"
        })
    
    # Latest 10 challenge purchases
    purchases = ChallengePurchase.query.order_by(
        ChallengePurchase.purchase_date.desc()
    ).limit(10).all()
    for p in purchases:
        events.append({
            'timestamp': p.purchase_date.isoformat() if p.purchase_date else None,
            'type': 'challenge_purchase',
            'user': p.user.get_full_name() if p.user else 'Unknown',
            'description': f"Purchased {p.challenge_template.name if p.challenge_template else 'Challenge'}"
        })
    
    # Latest 10 payments
    payments_list = Payment.query.order_by(Payment.created_at.desc()).limit(10).all()
    for p in payments_list:
        status_lower = (p.status or '').lower()
        if 'success' in status_lower:
            event_type = 'payment_success'
        elif 'fail' in status_lower:
            event_type = 'payment_failed'
        else:
            event_type = 'payment'
            
        events.append({
            'timestamp': p.created_at.isoformat() if p.created_at else None,
            'type': event_type,
            'user': p.user.get_full_name() if p.user else 'Unknown',
            'description': f"Payment of ₹{float(p.amount or 0):,.2f} - {p.status}"
        })
    
    # Latest 10 KYC submissions
    kyc_users = User.query.filter(
        User.kyc_status.in_(['submitted', 'approved', 'rejected'])
    ).order_by(User.kyc_submitted_at.desc().nullslast()).limit(10).all()
    for u in kyc_users:
        events.append({
            'timestamp': u.kyc_submitted_at.isoformat() if u.kyc_submitted_at else None,
            'type': f"kyc_{u.kyc_status}",
            'user': u.get_full_name(),
            'description': f"KYC {u.kyc_status}"
        })
    
    # Latest 10 support tickets
    tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).limit(10).all()
    for t in tickets:
        events.append({
            'timestamp': t.created_at.isoformat() if t.created_at else None,
            'type': 'support_ticket',
            'user': t.user.get_full_name() if t.user else 'Unknown',
            'description': f"Ticket #{t.ticket_number}: {(t.subject or '')[:50]}"
        })
    
    # Latest 5 coupon usages
    usages = CouponUsage.query.order_by(CouponUsage.used_at.desc()).limit(5).all()
    for u in usages:
        events.append({
            'timestamp': u.used_at.isoformat() if u.used_at else None,
            'type': 'coupon_used',
            'user': u.user.get_full_name() if u.user else 'Unknown',
            'description': f"Used coupon {u.coupon.code if u.coupon else 'Unknown'}"
        })
    
    # Sort by timestamp descending and take top 50
    events.sort(key=lambda x: x['timestamp'] or '1970-01-01', reverse=True)
    events = events[:50]
    
    return jsonify({'success': True, 'events': events})




# ========================================================================
# VIOLATION REPORT CENTER
# ========================================================================

@admin_bp.route('/violations')
@admin_required
def admin_violations():
    """Violation Report Center - List all violations"""
    from models import ViolationEvidence
    
    page = request.args.get('page', 1, type=int)
    violation_type = request.args.get('type', 'all')
    review_status = request.args.get('reviewed', 'all')
    
    query = ViolationEvidence.query
    
    if violation_type != 'all':
        query = query.filter_by(violation_type=violation_type)
    
    if review_status == 'reviewed':
        query = query.filter_by(is_reviewed=True)
    elif review_status == 'unreviewed':
        query = query.filter_by(is_reviewed=False)
    
    violations = query.order_by(ViolationEvidence.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template('admin/violations_list.html', 
                         violations=violations,
                         violation_type=violation_type,
                         review_status=review_status)


@admin_bp.route('/violations/<int:evidence_id>')
@admin_required
def admin_violation_detail(evidence_id):
    """View complete violation evidence package"""
    from models import ViolationEvidence
    
    evidence = ViolationEvidence.query.get_or_404(evidence_id)
    challenge = ChallengePurchase.query.get(evidence.challenge_purchase_id)
    
    return render_template('admin/violation_detail.html',
                         evidence=evidence,
                         challenge=challenge)


@admin_bp.route('/violations/<int:evidence_id>/action', methods=['POST'])
@admin_required
def admin_violation_action(evidence_id):
    """Admin action on violation: confirm fail or clear"""
    from models import ViolationEvidence
    
    evidence = ViolationEvidence.query.get_or_404(evidence_id)
    challenge = ChallengePurchase.query.get(evidence.challenge_purchase_id)
    admin_user = User.query.get(session['user_id'])
    action = request.form.get('action')
    notes = request.form.get('notes', '')
    now = datetime.now(timezone.utc)
    
    if action == 'confirm_fail':
        # Fail the challenge
        challenge.status = 'failed'
        challenge.is_terminated = True
        challenge.monitoring_status = 'failed'
        challenge.review_required = False
        challenge.violation_reviewed = True
        challenge.completed_at = now
        
        # Update evidence record
        evidence.is_reviewed = True
        evidence.reviewed_by = admin_user.id
        evidence.reviewed_at = now
        evidence.review_decision = 'confirmed_fail'
        evidence.review_notes = notes
        
        # Log admin action (NOT visible to user)
        log_rule(challenge.id, "admin_confirmed_fail", "critical",
                f"Admin confirmed violation. Account failed.")
        
        # Notify user (NO admin name exposed)
        _notify_challenge_breached(challenge, admin_user.id)
        
        flash('Violation confirmed. Account has been failed.', 'success')
        
    elif action == 'clear_violation':
        # Clear the violation, restore account to active
        challenge.status = 'active'
        challenge.monitoring_status = 'active'
        challenge.review_required = False
        challenge.violation_reason = None
        challenge.violation_reviewed = True
        challenge.risk_score = max(0, (challenge.risk_score or 0) - 30)
        
        # Reset manipulation baseline
        challenge.manipulation_check_baseline = challenge.current_balance
        challenge.manipulation_baseline_set_at = now
        
        # Update evidence record
        evidence.is_reviewed = True
        evidence.reviewed_by = admin_user.id
        evidence.reviewed_at = now
        evidence.review_decision = 'cleared'
        evidence.review_notes = notes
        
        # Log admin action
        log_rule(challenge.id, "admin_cleared_violation", "info",
                f"Admin cleared violation. Account restored to active.")
        
        # Notify user
        _notify_user(
            challenge.user_id,
            "Account Restored",
            "Your account has been reviewed and restored to active status. You may continue trading."
        )
        
        flash('Violation cleared. Account restored to active.', 'success')
    
    db.session.commit()
    return redirect(url_for('admin.admin_violation_detail', evidence_id=evidence_id))


@admin_bp.route('/api/violations/<int:evidence_id>')
@admin_required
def api_violation_detail(evidence_id):
    """API endpoint for violation evidence"""
    from models import ViolationEvidence
    
    evidence = ViolationEvidence.query.get_or_404(evidence_id)
    return jsonify({
        'success': True,
        'evidence': evidence.to_dict()
    })


@admin_bp.route('/api/challenge/<int:challenge_id>/violations')
@admin_required
def api_challenge_violations_list(challenge_id):
    """Get all violations for a specific challenge"""
    from models import ViolationEvidence
    
    violations = ViolationEvidence.query.filter_by(
        challenge_purchase_id=challenge_id
    ).order_by(ViolationEvidence.created_at.desc()).all()
    
    return jsonify({
        'success': True,
        'violations': [v.to_dict() for v in violations]
    })
# ========================================================================
# LEAD CRM ROUTES (NEW)
# ========================================================================
from models import LeadStatus, LeadNote, FollowUp
from datetime import datetime, timezone
from sqlalchemy import or_


@admin_bp.route('/leads')
@admin_required
def leads():
    return render_template('admin/leads.html')


@admin_bp.route('/leads/<int:lead_id>')
@admin_required
def lead_detail(lead_id):
    lead = User.query.get_or_404(lead_id)
    lead_status = LeadStatus.query.get(lead.lead_status_id) if lead.lead_status_id else None
    all_statuses = LeadStatus.query.order_by(LeadStatus.display_order).all()
    return render_template('admin/leads_detail.html', lead=lead, lead_status=lead_status, all_statuses=all_statuses)


@admin_bp.route('/leads/api/stats')
@admin_required
def leads_api_stats():
    try:
        statuses = LeadStatus.query.all()
        status_counts = {s.name: s.users.count() for s in statuses}
        return jsonify({'success': True, 'status_counts': status_counts})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/statuses')
@admin_required
def leads_api_statuses():
    try:
        statuses = LeadStatus.query.order_by(LeadStatus.display_order).all()
        return jsonify({'success': True, 'statuses': [s.to_dict() for s in statuses]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/statuses/custom', methods=['POST'])
@admin_required
def leads_api_create_status():
    try:
        data = request.get_json()
        name = (data.get('name') or '').strip()
        color = data.get('color') or '#6B7280'
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'})
        if LeadStatus.query.filter_by(name=name).first():
            return jsonify({'success': False, 'error': 'A status with this name already exists'})
        max_order = db.session.query(db.func.max(LeadStatus.display_order)).scalar() or 0
        status = LeadStatus(name=name, color=color, is_default=False, display_order=max_order + 1)
        db.session.add(status)
        db.session.commit()
        return jsonify({'success': True, 'status': status.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/statuses/<int:status_id>', methods=['PUT'])
@admin_required
def leads_api_edit_status(status_id):
    try:
        status = LeadStatus.query.get_or_404(status_id)
        data = request.get_json()
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'})
        status.name = name
        status.color = data.get('color') or status.color
        db.session.commit()
        return jsonify({'success': True, 'status': status.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/statuses/<int:status_id>', methods=['DELETE'])
@admin_required
def leads_api_delete_status(status_id):
    try:
        status = LeadStatus.query.get_or_404(status_id)
        if status.is_default:
            return jsonify({'success': False, 'error': 'Cannot delete a default status'})
        User.query.filter_by(lead_status_id=status_id).update({'lead_status_id': None})
        db.session.delete(status)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/list')
@admin_required
def leads_api_list():
    try:
        page = request.args.get('page', 1, type=int)
        search = (request.args.get('search') or '').strip()
        status = request.args.get('status', 'all')
        per_page = 20

        query = User.query.filter(User.is_admin == False)

        if status == 'none':
            query = query.filter(User.lead_status_id.is_(None))
        elif status != 'all':
            query = query.join(LeadStatus, User.lead_status_id == LeadStatus.id).filter(LeadStatus.name == status)

        if search:
            like = f'%{search}%'
            query = query.filter(or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                User.phone.ilike(like)
            ))

        query = query.order_by(User.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        leads_out = [{
            'id': u.id,
            'name': u.get_full_name(),
            'email': u.email,
            'phone': u.phone,
            'status_name': u.lead_status.name if u.lead_status else None,
            'status_color': u.lead_status.color if u.lead_status else None,
            'kyc_status': u.kyc_status
        } for u in pagination.items]

        return jsonify({
            'success': True,
            'leads': leads_out,
            'total': pagination.total,
            'pages': pagination.pages or 1,
            'page': page
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/<int:lead_id>/status', methods=['POST'])
@admin_required
def leads_api_change_status(lead_id):
    try:
        user = User.query.get_or_404(lead_id)
        data = request.get_json()
        user.lead_status_id = data.get('status_id')
        user.last_contacted_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/<int:lead_id>/notes', methods=['GET', 'POST'])
@admin_required
def leads_api_notes(lead_id):
    try:
        if request.method == 'POST':
            data = request.get_json()
            content = (data.get('content') or '').strip()
            if not content:
                return jsonify({'success': False, 'error': 'Note content is required'})
            note = LeadNote(user_id=lead_id, admin_id=session.get('user_id'), content=content)
            db.session.add(note)
            db.session.commit()
            return jsonify({'success': True, 'note': note.to_dict()})
        notes = LeadNote.query.filter_by(user_id=lead_id).order_by(LeadNote.created_at.desc()).all()
        return jsonify({'success': True, 'notes': [n.to_dict() for n in notes]})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/notes/<int:note_id>', methods=['DELETE'])
@admin_required
def leads_api_delete_note(note_id):
    try:
        note = LeadNote.query.get_or_404(note_id)
        db.session.delete(note)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/<int:lead_id>/followups', methods=['GET', 'POST'])
@admin_required
def leads_api_followups(lead_id):
    try:
        if request.method == 'POST':
            data = request.get_json()
            followup_date_str = data.get('followup_date')
            if not followup_date_str:
                return jsonify({'success': False, 'error': 'Follow-up date is required'})
            followup = FollowUp(
                user_id=lead_id,
                admin_id=session.get('user_id'),
                followup_date=datetime.fromisoformat(followup_date_str),
                followup_type=data.get('followup_type', 'Call'),
                notes=data.get('notes', '')
            )
            db.session.add(followup)
            db.session.commit()
            return jsonify({'success': True, 'followup': followup.to_dict()})
        followups = FollowUp.query.filter_by(user_id=lead_id).order_by(FollowUp.followup_date.desc()).all()
        return jsonify({'success': True, 'followups': [f.to_dict() for f in followups]})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/followups/<int:followup_id>/complete', methods=['POST'])
@admin_required
def leads_api_complete_followup(followup_id):
    try:
        followup = FollowUp.query.get_or_404(followup_id)
        followup.is_completed = True
        followup.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/bulk-action', methods=['POST'])
@admin_required
def leads_api_bulk_action():
    try:
        data = request.get_json()
        action = data.get('action')
        lead_ids = data.get('lead_ids', [])
        if not lead_ids:
            return jsonify({'success': False, 'error': 'No leads selected'})

        if action == 'move_status':
            User.query.filter(User.id.in_(lead_ids)).update(
                {'lead_status_id': data.get('status_id')}, synchronize_session=False)
            db.session.commit()
            return jsonify({'success': True})
        elif action == 'add_note':
            note_content = (data.get('note') or '').strip()
            if not note_content:
                return jsonify({'success': False, 'error': 'Note content is required'})
            admin_id = session.get('user_id')
            for uid in lead_ids:
                db.session.add(LeadNote(user_id=uid, admin_id=admin_id, content=note_content))
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Unknown action'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})
# ========================================================================
# AFFILIATE REWARDS ROUTES
# ========================================================================

@admin_bp.route('/affiliate-rewards')
@admin_required
def admin_affiliate_rewards():
    """Affiliate & Rewards management dashboard"""
    from models import AffiliateSettings, Wallet, ReferralReward, WithdrawalRequest, AffiliateViolation
    
    settings = AffiliateSettings.get_settings()
    
    # Stats
    affiliate_users = User.query.filter_by(role='partner', is_banned=False).count()
    referral_sales = ReferralReward.query.filter_by(status='approved').count()
    discounts = db.session.query(db.func.sum(ReferralReward.discount_given)).filter_by(status='approved').scalar() or 0.0
    wallet_rewards = db.session.query(db.func.sum(Wallet.current_balance)).scalar() or 0.0
    pending_withdrawals = WithdrawalRequest.query.filter_by(status='pending').count()
    
    stats = {
        'affiliate_users': affiliate_users,
        'referral_sales': referral_sales,
        'discounts': discounts,
        'wallet_rewards': wallet_rewards,
        'pending_withdrawals': pending_withdrawals
    }
    
    # Affiliate users with wallets
    affiliate_users_list = User.query.filter_by(role='partner').all()
    
    # Recent referrals
    referrals = ReferralReward.query.order_by(ReferralReward.created_at.desc()).limit(20).all()
    
    # Pending withdrawals
    withdrawals = WithdrawalRequest.query.filter(WithdrawalRequest.status.in_(['pending', 'approved'])).order_by(WithdrawalRequest.requested_at.desc()).limit(20).all()
    
    # Recent violations
    violations = AffiliateViolation.query.filter_by(is_resolved=False).order_by(AffiliateViolation.created_at.desc()).limit(20).all()
    
    return render_template('admin/affiliate_rewards.html',
                         stats=stats,
                         settings=settings,
                         affiliate_users=affiliate_users_list,
                         referrals=referrals,
                         withdrawals=withdrawals,
                         violations=violations)


@admin_bp.route('/affiliate-rewards/settings', methods=['POST'])
@admin_required
def update_affiliate_settings():
    """Update affiliate program settings"""
    from models import AffiliateSettings
    
    settings = AffiliateSettings.get_settings()
    settings.buyer_discount_amount = float(request.form.get('buyer_discount_amount', 0))
    settings.referrer_reward_amount = float(request.form.get('referrer_reward_amount', 0))
    settings.minimum_withdrawal_amount = float(request.form.get('minimum_withdrawal_amount', 150))
    settings.affiliate_enabled = 'affiliate_enabled' in request.form
    settings.cash_withdrawal_enabled = 'cash_withdrawal_enabled' in request.form
    settings.coupon_conversion_enabled = 'coupon_conversion_enabled' in request.form
    settings.updated_by_admin_id = session.get('user_id')
    
    db.session.commit()
    flash('Affiliate settings updated successfully.', 'success')
    return redirect(url_for('admin.admin_affiliate_rewards'))


@admin_bp.route('/affiliate-rewards/moderate/<int:user_id>/<action>', methods=['POST'])
@admin_required
def moderate_affiliate(user_id, action):
    """Enable, disable, ban, unban, or reset affiliate code"""
    from models import AdminLog
    
    user = User.query.get_or_404(user_id)
    
    if action == 'enable':
        user.affiliate_enabled = True
        user.affiliate_banned = False
        flash(f'Affiliate {user.email} enabled.', 'success')
    elif action == 'disable':
        reason = request.form.get('reason', '')
        user.affiliate_enabled = False
        user.affiliate_disabled_reason = reason
        flash(f'Affiliate {user.email} disabled.', 'success')
    elif action == 'ban':
        user.affiliate_banned = True
        user.affiliate_enabled = False
        flash(f'Affiliate {user.email} banned.', 'success')
    elif action == 'unban':
        user.affiliate_banned = False
        user.affiliate_enabled = True
        flash(f'Affiliate {user.email} unbanned.', 'success')
    elif action == 'reset-code':
        import secrets, string
        user.affiliate_code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        user.affiliate_code_reset_at = datetime.now(timezone.utc)
        flash(f'Affiliate code reset for {user.email}. New code: {user.affiliate_code}', 'success')
    
    db.session.commit()
    return redirect(url_for('admin.admin_affiliate_rewards'))


@admin_bp.route('/affiliate-rewards/adjust-wallet/<int:user_id>', methods=['POST'])
@admin_required
def adjust_wallet(user_id):
    """Add or remove funds from affiliate wallet"""
    from models import Wallet, WalletTransaction
    
    user = User.query.get_or_404(user_id)
    wallet = Wallet.get_or_create(user_id)
    
    action = request.form.get('action')
    amount = float(request.form.get('amount', 0))
    
    if amount <= 0:
        flash('Amount must be positive.', 'error')
        return redirect(url_for('admin.admin_affiliate_rewards'))
    
    if action == 'add':
        wallet.current_balance += amount
        wallet.lifetime_earned += amount
        txn_type = 'credit'
        notes = f'Admin adjustment: +{amount}'
    elif action == 'remove':
        wallet.current_balance = max(0, wallet.current_balance - amount)
        txn_type = 'debit'
        notes = f'Admin adjustment: -{amount}'
    else:
        flash('Invalid action.', 'error')
        return redirect(url_for('admin.admin_affiliate_rewards'))
    
    txn = WalletTransaction(
        wallet_id=wallet.id,
        user_id=user_id,
        amount=amount,
        transaction_type=txn_type,
        source='admin_adjustment',
        status='completed',
        notes=notes,
        admin_id=session.get('user_id')
    )
    db.session.add(txn)
    db.session.commit()
    
    flash(f'Wallet adjusted for {user.email}. New balance: Rs. {wallet.current_balance:.2f}', 'success')
    return redirect(url_for('admin.admin_affiliate_rewards'))


@admin_bp.route('/affiliate-rewards/withdrawal/<int:withdrawal_id>/<action>', methods=['POST'])
@admin_required
def update_wallet_withdrawal(withdrawal_id, action):
    """Approve, reject, or mark withdrawal as paid"""
    from models import WithdrawalRequest, Wallet, WalletTransaction
    
    withdrawal = WithdrawalRequest.query.get_or_404(withdrawal_id)
    admin_id = session.get('user_id')
    
    if action == 'approve':
        if withdrawal.status != 'pending':
            flash('Only pending withdrawals can be approved.', 'error')
            return redirect(url_for('admin.admin_affiliate_rewards'))
        withdrawal.status = 'approved'
        withdrawal.reviewed_at = datetime.now(timezone.utc)
        withdrawal.reviewed_by_admin_id = admin_id
        flash('Withdrawal approved.', 'success')
    
    elif action == 'reject':
        if withdrawal.status not in ['pending', 'approved']:
            flash('Cannot reject this withdrawal.', 'error')
            return redirect(url_for('admin.admin_affiliate_rewards'))
        # Refund the amount back to wallet
        wallet = Wallet.get_or_create(withdrawal.user_id)
        wallet.current_balance += withdrawal.amount
        wallet.pending_balance = max(0, wallet.pending_balance - withdrawal.amount)
        
        txn = WalletTransaction(
            wallet_id=wallet.id,
            user_id=withdrawal.user_id,
            amount=withdrawal.amount,
            transaction_type='credit',
            source='withdrawal_rejected',
            status='completed',
            notes=f'Withdrawal #{withdrawal.id} rejected',
            admin_id=admin_id
        )
        db.session.add(txn)
        
        withdrawal.status = 'rejected'
        withdrawal.reviewed_at = datetime.now(timezone.utc)
        withdrawal.reviewed_by_admin_id = admin_id
        flash('Withdrawal rejected. Amount returned to wallet.', 'success')
    
    elif action == 'paid':
        if withdrawal.status != 'approved':
            flash('Only approved withdrawals can be marked as paid.', 'error')
            return redirect(url_for('admin.admin_affiliate_rewards'))
        transaction_id = request.form.get('transaction_id', '').strip()
        if not transaction_id:
            flash('Transaction ID is required.', 'error')
            return redirect(url_for('admin.admin_affiliate_rewards'))
        withdrawal.status = 'paid'
        withdrawal.transaction_id = transaction_id
        withdrawal.paid_at = datetime.now(timezone.utc)
        
        # Update wallet
        wallet = Wallet.get_or_create(withdrawal.user_id)
        wallet.lifetime_withdrawn += withdrawal.amount
        wallet.pending_balance = max(0, wallet.pending_balance - withdrawal.amount)
        
        flash('Withdrawal marked as paid.', 'success')
    
    db.session.commit()
    return redirect(url_for('admin.admin_affiliate_rewards'))
# ========================================================================
# SURVEYS ROUTES
# ========================================================================

@admin_bp.route('/surveys', methods=['GET', 'POST'])
@admin_required
def admin_surveys():
    """Survey management - create, view, assign surveys"""
    from models import Survey, SurveyQuestion, SurveyAssignment
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        survey_type = request.form.get('survey_type', 'text')
        reward_amount = float(request.form.get('reward_amount', 0))
        description = request.form.get('description', '').strip()
        questions_text = request.form.get('questions', '').strip()
        
        if not title or reward_amount <= 0:
            flash('Title and reward amount are required.', 'error')
            return redirect(url_for('admin.admin_surveys'))
        
        survey = Survey(
            title=title,
            description=description,
            survey_type=survey_type,
            reward_amount=reward_amount,
            created_by_admin_id=session.get('user_id')
        )
        db.session.add(survey)
        db.session.flush()
        
        if questions_text:
            for i, line in enumerate(questions_text.split('\n')):
                line = line.strip()
                if line:
                    db.session.add(SurveyQuestion(
                        survey_id=survey.id,
                        question_text=line,
                        display_order=i
                    ))
        
        db.session.commit()
        flash('Survey created successfully!', 'success')
        return redirect(url_for('admin.admin_surveys'))
    
    surveys = Survey.query.order_by(Survey.created_at.desc()).all()
    users = User.query.filter_by(is_admin=False).order_by(User.email).all()
    assignments = SurveyAssignment.query.order_by(SurveyAssignment.assigned_at.desc()).limit(50).all()
    
    return render_template('admin/surveys.html',
                         surveys=surveys,
                         users=users,
                         assignments=assignments)


@admin_bp.route('/surveys/assign/<int:survey_id>', methods=['POST'])
@admin_required
def assign_survey(survey_id):
    """Assign survey to users based on target filter"""
    from models import Survey, SurveyAssignment
    
    survey = Survey.query.get_or_404(survey_id)
    target = request.form.get('target', 'all')
    selected_ids = request.form.getlist('user_ids')
    
    if target == 'all':
        users = User.query.filter_by(is_admin=False).all()
    elif target == 'kyc_approved':
        users = User.query.filter_by(kyc_status='approved', is_admin=False).all()
    elif target == 'active_traders':
        active_challenge_users = db.session.query(ChallengePurchase.user_id).filter(
            ChallengePurchase.status.in_(['active', 'funded'])
        ).distinct().all()
        active_ids = [u[0] for u in active_challenge_users]
        users = User.query.filter(User.id.in_(active_ids), User.is_admin == False).all()
    elif target == 'affiliate_users':
        users = User.query.filter_by(role='partner', is_banned=False).all()
    elif target == 'selected':
        if not selected_ids:
            flash('No users selected.', 'error')
            return redirect(url_for('admin.admin_surveys'))
        users = User.query.filter(User.id.in_(selected_ids)).all()
    else:
        flash('Invalid target.', 'error')
        return redirect(url_for('admin.admin_surveys'))
    
    assigned = 0
    for user in users:
        existing = SurveyAssignment.query.filter_by(
            survey_id=survey.id, user_id=user.id
        ).first()
        if not existing:
            db.session.add(SurveyAssignment(
                survey_id=survey.id,
                user_id=user.id,
                status='assigned' if survey.survey_type == 'text' else 'waiting_for_call'
            ))
            assigned += 1
    
    db.session.commit()
    flash(f'Survey assigned to {assigned} users.', 'success')
    return redirect(url_for('admin.admin_surveys'))


@admin_bp.route('/surveys/grant-reward/<int:assignment_id>', methods=['POST'])
@admin_required
def grant_call_survey_reward(assignment_id):
    """Grant reward for completed call survey"""
    from models import SurveyAssignment, Wallet, WalletTransaction
    
    assignment = SurveyAssignment.query.get_or_404(assignment_id)
    
    if assignment.survey.survey_type != 'call' or assignment.status != 'waiting_for_call':
        flash('Invalid assignment for reward.', 'error')
        return redirect(url_for('admin.admin_surveys'))
    
    reward = assignment.survey.reward_amount
    wallet = Wallet.get_or_create(assignment.user_id)
    wallet.current_balance += reward
    wallet.lifetime_earned += reward
    
    txn = WalletTransaction(
        wallet_id=wallet.id,
        user_id=assignment.user_id,
        amount=reward,
        transaction_type='credit',
        source='survey_reward',
        status='completed',
        notes=f'Reward for survey: {assignment.survey.title}',
        admin_id=session.get('user_id')
    )
    db.session.add(txn)
    
    assignment.status = 'rewarded'
    assignment.rewarded_at = datetime.now(timezone.utc)
    assignment.reward_transaction_id = txn.id  # Will be set after flush
    
    db.session.flush()
    txn.reference_type = 'survey_assignment'
    txn.reference_id = assignment.id
    
    db.session.commit()
    flash(f'Reward of Rs. {reward:.2f} granted to {assignment.user.email}.', 'success')
    return redirect(url_for('admin.admin_surveys'))