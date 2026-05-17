from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort
from functools import wraps
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, FAQ, SupportTicket, TicketMessage
from datetime import datetime, timedelta, timezone
import secrets

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

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
    
    return render_template('admin/admin_dashboard.html', 
                         total_users=total_users,
                         pending_kyc=pending_kyc,
                         approved_kyc=approved_kyc,
                         recent_users=recent_users)

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
        db.session.commit()
        flash(f'Approved {len(users)} KYC applications.', 'success')
    elif action == 'reject':
        for user in users:
            user.kyc_status = 'rejected'
            user.kyc_notes = 'Bulk rejection'
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
                purchase.current_phase = 2
                purchase.status = 'phase2_active'
                purchase.phase = 2
            else:
                purchase.current_phase = 3
                purchase.status = 'funded_active'
                purchase.phase = 3
            
        elif action == 'force_pass_phase2':
            purchase.current_phase = 3
            purchase.status = 'funded_active'
            purchase.phase = 3
            
        elif action == 'force_pass_all':
            purchase.current_phase = 3
            purchase.status = 'funded_active'
            purchase.phase = 3
            
        elif action == 'force_fail':
            purchase.status = 'breached'
            purchase.is_terminated = True
            purchase.credentials_revoked_at = datetime.now(timezone.utc)
            
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
                    purchase.current_phase = 2
                    purchase.status = 'phase2_active'
                    purchase.phase = 2
                else:
                    purchase.current_phase = 3
                    purchase.status = 'funded_active'
                    purchase.phase = 3
                
            elif action == 'force_pass_phase2':
                purchase.current_phase = 3
                purchase.status = 'funded_active'
                purchase.phase = 3
                
            elif action == 'force_pass_all':
                purchase.current_phase = 3
                purchase.status = 'funded_active'
                purchase.phase = 3
                
            elif action == 'force_fail':
                purchase.status = 'breached'
                purchase.is_terminated = True
                purchase.credentials_revoked_at = datetime.now(timezone.utc)
                
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
        challenge.phase1_overall_loss = None
        challenge.phase1_min_days = None
        challenge.phase1_duration = None
        challenge.phase1_leverage = None
        challenge.phase1_rules = None
        
        challenge.phase2_target = None
        challenge.phase2_daily_loss = None
        challenge.phase2_overall_loss = None
        challenge.phase2_min_days = None
        challenge.phase2_duration = None
        challenge.phase2_leverage = None
        challenge.phase2_rules = None
        
        challenge.instant_daily_loss = None
        challenge.instant_overall_loss = None
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
            challenge.phase1_overall_loss = get_float('phase1_overall_loss')
            challenge.phase1_min_days = get_int('phase1_min_days')
            challenge.phase1_duration = get_int('phase1_duration')
            challenge.phase1_leverage = request.form.get('phase1_leverage')
            challenge.phase1_rules = request.form.get('phase1_rules_text', '')
            
            if ctype == 'two_phase':
                challenge.phase2_target = get_float('phase2_target')
                challenge.phase2_daily_loss = get_float('phase2_daily_loss')
                challenge.phase2_overall_loss = get_float('phase2_overall_loss')
                challenge.phase2_min_days = get_int('phase2_min_days')
                challenge.phase2_duration = get_int('phase2_duration')
                challenge.phase2_leverage = request.form.get('phase2_leverage')
                challenge.phase2_rules = request.form.get('phase2_rules_text', '')
                
        elif ctype == 'instant':
            challenge.instant_daily_loss = get_float('instant_daily_loss')
            challenge.instant_overall_loss = get_float('instant_overall_loss')
            challenge.instant_min_days = get_int('instant_min_days')
            challenge.instant_leverage = request.form.get('instant_leverage')
            challenge.instant_rules = request.form.get('instant_rules_text', '')

        challenge.user_profit_share = int(request.form.get('user_profit_share', 0))
        challenge.payout_cycle = request.form.get('payout_cycle', 'biweekly')
        challenge.weekend_trading = 'weekend_trading' in request.form
        challenge.is_active = 'is_active' in request.form
        challenge.description = request.form.get('description', '')
        
        if not challenge_id:
            db.session.add(challenge)
        
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
        
    if refund != 'all':
        if refund == 'eligible':
            pass  # refund filter removed
        elif refund == 'refunded':
            pass  # refund filter removed
        elif refund == 'not_eligible':
            pass  # refund filter removed
            
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
    # Pagination params
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except (ValueError, TypeError):
        page = 1
    
    try:
        per_page = min(max(int(request.args.get('per_page', 20)), 10), 100)
    except (ValueError, TypeError):
        per_page = 20
        
    search = request.args.get('search', '').strip()
    # Base query
    query = User.query
    # Search across multiple fields if provided
    if search:
        like = f"%{search}%"
        # Safe fallback if attributes don't exist
        query = query.filter(
            (User.first_name.ilike(like)) |
            (User.last_name.ilike(like)) |
            (User.email.ilike(like)) |
            (User.phone.ilike(like))
        )
    # Account status filter
    account_status = request.args.get('account_status', 'all')
    if account_status != 'all':
        if account_status == 'active':
            query = query.filter(User.is_active == True)
        elif account_status == 'banned':
            query = query.filter(User.is_banned == True)
        elif account_status == 'new':
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            query = query.filter(User.created_at >= week_ago)
    # KYC status filter
    kyc_status = request.args.get('kyc_status', 'all')
    if kyc_status != 'all':
        query = query.filter(User.kyc_status == kyc_status)
        
    # Sorting
    sort = request.args.get('sort', 'newest')
    if sort == 'oldest':
        query = query.order_by(User.created_at.asc())
    else:  # newest (default)
        query = query.order_by(User.created_at.desc())
        
    # Pagination
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
    # Safely fetch related data using hasattr or getattr
    challenges = getattr(user, 'challenge_purchases', []) if hasattr(user, 'challenge_purchases') else []
    payments = getattr(user, 'payments', []) if hasattr(user, 'payments') else []
    support_tickets = getattr(user, 'support_tickets', []) if hasattr(user, 'support_tickets') else []
    payouts = getattr(user, 'payouts', []) if hasattr(user, 'payouts') else []
    
    # Calculate financial stats
    total_spent = sum(p.amount for p in payments if p.status.upper() == 'SUCCESS')
    total_purchases = len([p for p in payments if p.status.upper() == 'SUCCESS'])
    total_payouts = sum(p.amount for p in payouts if p.status.upper() == 'SUCCESS' or p.status.upper() == 'PAID')
    
    referrals = []  # Placeholder; will be populated if referral system exists
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
    
    active_challenges = ChallengePurchase.query.filter_by(status='active').count()
    expiring_soon = ChallengePurchase.query.filter(
        ChallengePurchase.status == 'active',
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
        'expiring_soon': expiring_soon,
        'payout_eligible': payout_eligible
    }

@admin_bp.route('/payment/<int:payment_id>/mark-refund', methods=['POST'])
@admin_required
def admin_mark_refund(payment_id):
    from models import Payment, AdminAuditLog
    payment = Payment.query.get_or_404(payment_id)
    
    if False:  # refund not implemented
        return jsonify({'success': False, 'message': 'Already marked eligible.'})
        
    if payment.status.lower() != 'success':
        return jsonify({'success': False, 'message': 'Cannot refund failed payment.'})
        
    pass  # refund not implemented
    pass  # refund not implemented
    
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
    
    if True:  # refund not implemented
        return jsonify({'success': False, 'message': 'Payment must be marked eligible first.'})
        
    if False:  # refund not implemented
        return jsonify({'success': False, 'message': 'Payment is already refunded.'})
        
    if payment.status.lower() != 'success':
        return jsonify({'success': False, 'message': 'Payment was not successful.'})
        
    if payment.amount and payment.amount <= 0:
        if payment.amount <= 0:
            return jsonify({'success': False, 'message': 'Payment amount is 0.'})
            
    # Mock Cashfree refund API logic here
    # In production, this would call Cashfree APIs via Celery
    
    pass  # refund not implemented
    pass  # refund not implemented
    payment.refund_verified_by = session.get('user_id')
    payment.status = 'refunded'
    
    audit = AdminAuditLog(
        admin_id=session.get('user_id'),
        action='executed_refund',
        payment_id=payment.id,
        old_value='none',
        new_value='refunded',
        ip_address=request.remote_addr
    )
    db.session.add(audit)
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Payment {payment.payment_id} successfully refunded.'})

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
    
    # This would generate a CSV file - you can implement the export logic
    flash('Export feature would generate CSV file with payment data.', 'info')
    return redirect(url_for('admin.admin_payments'))

# ===== CHALLENGE MANAGEMENT ROUTES =====

@admin_bp.route('/challenges')
@admin_required
def admin_challenges():
    """List all challenge purchases with search"""
    search_query = request.args.get('search', '').strip()
    
    query = db.session.query(ChallengePurchase).join(User).join(ChallengeTemplate)
    
    if search_query:
        # Search by serial_no or user email
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
    
    # Mark as read by admin
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
    
    # Save attachment if exists
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
    
    # Update ticket status to in_progress if it was open
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
