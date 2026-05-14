from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
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
            purchase.status = 'passed'
            if purchase.phase == 1:
                phase2_template = ChallengeTemplate.query.filter_by(
                    phase=2, 
                    account_size=purchase.challenge_template.account_size
                ).first()
                
                if phase2_template:
                    phase2_purchase = ChallengePurchase(
                        user_id=purchase.user_id,
                        challenge_template_id=phase2_template.id,
                        phase=2,
                        start_date=datetime.now(timezone.utc),
                        end_date=datetime.now(timezone.utc) + timedelta(days=phase2_template.duration_days),
                        status='active',
                        mt5_account=f"TRG_{purchase.user.first_name}_{purchase.user.id}_P2_{secrets.token_hex(4)}"
                    )
                    db.session.add(phase2_purchase)
            
        elif action == 'force_pass_phase2':
            purchase.status = 'passed'
            
        elif action == 'force_pass_all':
            purchase.status = 'passed'
            
        elif action == 'force_fail':
            purchase.status = 'failed'
            
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
                purchase.status = 'passed'
                if purchase.phase == 1:
                    phase2_template = ChallengeTemplate.query.filter_by(
                        phase=2, 
                        account_size=purchase.challenge_template.account_size
                    ).first()
                    
                    if phase2_template:
                        phase2_purchase = ChallengePurchase(
                            user_id=purchase.user_id,
                            challenge_template_id=phase2_template.id,
                            phase=2,
                            start_date=datetime.now(timezone.utc),
                            end_date=datetime.now(timezone.utc) + timedelta(days=phase2_template.duration_days),
                            status='active',
                            mt5_account=f"TRG_{purchase.user.first_name}_{purchase.user.id}_P2_{secrets.token_hex(4)}"
                        )
                        db.session.add(phase2_purchase)
                        
            elif action == 'force_pass_phase2':
                purchase.status = 'passed'
                
            elif action == 'force_pass_all':
                purchase.status = 'passed'
                
            elif action == 'force_fail':
                purchase.status = 'failed'
                
            elif action.startswith('extend_'):
                days = int(action.split('_')[1])
                if purchase.end_date:
                    purchase.end_date += timedelta(days=days)
        
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
    phase1_challenges = ChallengeTemplate.query.filter_by(phase=1).all()
    phase2_challenges = ChallengeTemplate.query.filter_by(phase=2).all()
    
    return render_template('admin/add_challenge.html',
                         phase1_challenges=phase1_challenges,
                         phase2_challenges=phase2_challenges)

@admin_bp.route('/save-challenge', methods=['POST'])
@admin_required
def admin_save_challenge():
    try:
        challenge_id = request.form.get('challenge_id')
        
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
        challenge.phase = int(request.form['phase'])
        challenge.profit_target = float(request.form['profit_target'])
        challenge.max_daily_loss = float(request.form['max_daily_loss'])
        challenge.max_overall_loss = float(request.form['max_overall_loss'])
        challenge.min_trading_days = int(request.form['min_trading_days'])
        challenge.duration_days = int(request.form['duration_days'])
        challenge.leverage = request.form['leverage']
        challenge.user_profit_share = int(request.form['user_profit_share'])
        challenge.payout_cycle = request.form['payout_cycle']
        challenge.weekend_trading = 'weekend_trading' in request.form
        challenge.is_active = 'is_active' in request.form
        challenge.description = request.form.get('description', '')
        
        if not challenge_id:
            db.session.add(challenge)
        
        db.session.commit()
        
        action = "updated" if challenge_id else "created"
        flash(f'Challenge {action} successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        print(f"Error saving challenge: {e}")
        flash('Error saving challenge. Please try again.', 'error')
    
    return redirect(url_for('admin.admin_manage_challenges'))

@admin_bp.route('/edit-challenge/<int:challenge_id>')
@admin_required
def admin_edit_challenge(challenge_id):
    challenge = ChallengeTemplate.query.get_or_404(challenge_id)
    phase1_challenges = ChallengeTemplate.query.filter_by(phase=1).all()
    phase2_challenges = ChallengeTemplate.query.filter_by(phase=2).all()
    
    return render_template('admin/add_challenge.html',
                         challenge=challenge,
                         phase1_challenges=phase1_challenges,
                         phase2_challenges=phase2_challenges)

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
    return redirect(url_for('admin.admin_users'))

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
    return redirect(url_for('admin.admin_users'))

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
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Build query
    query = Payment.query.join(User)
    
    # Apply status filter
    if status_filter != 'all':
        query = query.filter(Payment.status == status_filter)
    
    # Apply search filter
    if search_query:
        query = query.filter(
            (User.first_name.ilike(f'%{search_query}%')) |
            (User.last_name.ilike(f'%{search_query}%')) |
            (User.email.ilike(f'%{search_query}%')) |
            (Payment.payment_id.ilike(f'%{search_query}%')) |
            (Payment.gateway_id.ilike(f'%{search_query}%'))
        )
    
    # Get paginated results
    payments = query.order_by(Payment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Calculate stats
    total_revenue = db.session.query(db.func.sum(Payment.amount)).filter(
        Payment.status == 'success'
    ).scalar() or 0
    
    successful_payments = Payment.query.filter_by(status='success').count()
    pending_payments = Payment.query.filter_by(status='pending').count()
    failed_payments = Payment.query.filter_by(status='failed').count()
    refunded_payments = Payment.query.filter_by(status='refunded').count()
    
    return render_template('admin/payments.html',
                         payments=payments,
                         total_revenue=total_revenue,
                         successful_payments=successful_payments,
                         pending_payments=pending_payments,
                         failed_payments=failed_payments,
                         refunded_payments=refunded_payments,
                         status_filter=status_filter,
                         search_query=search_query)

@admin_bp.route('/activity')
@admin_required
def admin_activity():
    return render_template('admin/activity.html')

@admin_bp.route('/settings')
@admin_required
def admin_settings():
    return render_template('admin/settings.html')

@admin_bp.route('/user/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/user_detail.html', user=user)


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

@admin_bp.route('/payments/<int:payment_id>/refund')
@admin_required
def refund_payment(payment_id):
    from models import Payment
    
    payment = Payment.query.get_or_404(payment_id)
    
    if payment.status != 'success':
        flash('Can only refund successful payments.', 'error')
        return redirect(url_for('admin.admin_payments'))
    
    try:
        payment.status = 'refunded'
        db.session.commit()
        flash(f'Payment {payment.payment_id} has been refunded.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error refunding payment.', 'error')
    
    return redirect(url_for('admin.admin_payments'))

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

# ===== WAITLIST MANAGEMENT ROUTES =====
@admin_bp.route('/waitlist')
@admin_required
def admin_waitlist():
    from models import WaitlistLead
    
    # Filtering
    plan_filter = request.args.get('plan', 'all')
    experience_filter = request.args.get('experience', 'all')
    status_filter = request.args.get('status', 'all')
    early_access_filter = request.args.get('early_access', 'all')
    
    query = WaitlistLead.query
    
    if plan_filter != 'all':
        query = query.filter(WaitlistLead.plan_interest == plan_filter)
    if experience_filter != 'all':
        query = query.filter(WaitlistLead.experience == experience_filter)
    if status_filter != 'all':
        query = query.filter(WaitlistLead.status == status_filter)
    if early_access_filter == 'yes':
        query = query.filter(WaitlistLead.early_access == True)
    elif early_access_filter == 'no':
        query = query.filter(WaitlistLead.early_access == False)
        
    leads = query.order_by(WaitlistLead.created_at.desc()).all()
    
    return render_template('admin/waitlist_list.html', leads=leads, 
                           plan_filter=plan_filter, 
                           experience_filter=experience_filter, 
                           status_filter=status_filter, 
                           early_access_filter=early_access_filter)

@admin_bp.route('/waitlist/<int:lead_id>')
@admin_required
def admin_waitlist_detail(lead_id):
    from models import WaitlistLead
    lead = WaitlistLead.query.get_or_404(lead_id)
    return render_template('admin/waitlist_detail.html', lead=lead)

@admin_bp.route('/waitlist/<int:lead_id>/update-status', methods=['POST'])
@admin_required
def admin_waitlist_update_status(lead_id):
    from models import WaitlistLead
    lead = WaitlistLead.query.get_or_404(lead_id)
    new_status = request.form.get('status')
    
    if new_status in ['new', 'contacted', 'interested', 'converted']:
        lead.status = new_status
        db.session.commit()
        flash(f'Waitlist lead status updated to {new_status}.', 'success')
    else:
        flash('Invalid status.', 'error')
        
    return redirect(url_for('admin.admin_waitlist_detail', lead_id=lead_id))
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
        # Use simple allowed check
        def is_allowed(filename):
            return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'pdf'}
            
        if is_allowed(attachment.filename):
            from werkzeug.utils import secure_filename
            import os, time
            filename = secure_filename(f"admin_{ticket_number}_reply_{int(time.time())}_{attachment.filename}")
            upload_dir = os.path.join('static', 'uploads', 'tickets')
            os.makedirs(upload_dir, exist_ok=True)
            attachment.save(os.path.join(upload_dir, filename))
            attachment_url = f"uploads/tickets/{filename}"
    
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
