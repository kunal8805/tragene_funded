from flask import render_template, request, redirect, url_for, flash, session, jsonify, abort, Response, send_file
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, extract, or_
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, PayoutAuditLog, FAQ, SupportTicket, TicketMessage, Payment, AdminLog, Notification, UserNotification, NotificationTemplate, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection, LeadStatus, LeadNote, FollowUp
from . import admin_bp, admin_required, get_current_moderator, log_moderator_activity
from notification_service import create_notification
import secrets
import csv
import io
import json

from . import _admin_name, _notify_user, _notify_challenge_passed, _notify_challenge_breached, _activate_progression_stage, _payout_audit, _eligible_funded_count, _payout_stats

# Helper to get current user ID (works for both admin and moderator)
def _current_user_id():
    return session.get('user_id') or session.get('moderator_id')

# Helper to log moderator actions easily
def _log_if_moderator(module, action, description=None, target_type=None, target_id=None, before_state=None, after_state=None, status='success'):
    """Log action only if current user is a moderator"""
    if 'moderator_id' in session:
        try:
            log_moderator_activity(
                moderator_id=session['moderator_id'],
                module=module,
                action=action,
                description=description,
                target_type=target_type,
                target_id=target_id,
                before_state=before_state,
                after_state=after_state,
                status=status
            )
        except:
            pass  # Don't break functionality if logging fails

@admin_bp.route('/users')
@admin_required
def admin_users():
    users = []
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
    before_state = {'kyc_status': user.kyc_status}
    user.kyc_status = 'approved'
    user.kyc_notes = ''
    create_notification(
        user.id,
        'KYC Verified',
        'Congratulations! Your KYC has been successfully verified. You can now purchase challenges and participate fully on the platform.',
        'kyc',
        action_url='/challenges',
        icon='check',
        admin_id=_current_user_id(),
        dedupe_key=f'kyc-approved:{user.id}',
    )
    db.session.commit()
    
    _log_if_moderator('kyc', 'approved_kyc', f'Approved KYC for {user.email}', 'user', user.id, before_state, {'kyc_status': 'approved'})
    
    from email_service import send_automation_email
    send_automation_email('kyc_approved', user)
    
    flash(f'KYC for {user.email} has been approved.', 'success')
    return redirect(url_for('admin.admin_kyc'))


@admin_bp.route('/kyc/<int:user_id>/reject', methods=['POST'])
@admin_required
def admin_reject_kyc(user_id):
    user = User.query.get_or_404(user_id)
    rejection_reason = request.form.get('rejection_reason', 'Document not clear')
    before_state = {'kyc_status': user.kyc_status}
    user.kyc_status = 'rejected'
    user.kyc_notes = rejection_reason
    create_notification(
        user.id,
        'KYC Verification Failed',
        'Unfortunately your KYC verification was not approved. Please review the rejection reason and upload updated documents.',
        'kyc',
        action_url='/kyc',
        icon='warning',
        admin_id=_current_user_id(),
        dedupe_key=f'kyc-rejected:{user.id}:{datetime.now(timezone.utc).date().isoformat()}',
    )
    db.session.commit()
    
    _log_if_moderator('kyc', 'rejected_kyc', f'Rejected KYC for {user.email}: {rejection_reason}', 'user', user.id, before_state, {'kyc_status': 'rejected', 'reason': rejection_reason})
    
    flash(f'KYC for {user.email} has been rejected.', 'success')
    return redirect(url_for('admin.admin_kyc'))


@admin_bp.route('/kyc/<int:user_id>/delete')
@admin_required
def admin_delete_kyc(user_id):
    user = User.query.get_or_404(user_id)
    before_state = {'kyc_status': user.kyc_status}
    user.kyc_status = 'pending'
    user.id_front_url = ''
    user.id_back_url = ''
    user.document_type = ''
    user.kyc_submitted_at = None
    user.kyc_notes = ''
    db.session.commit()
    
    _log_if_moderator('kyc', 'cleared_kyc', f'Cleared KYC data for {user.email}', 'user', user.id, before_state, {'kyc_status': 'pending'})
    
    flash(f'KYC data cleared for {user.email}.', 'success')
    return redirect(url_for('admin.admin_kyc'))


@admin_bp.route('/bulk_kyc_action', methods=['POST'])
@admin_required
def admin_bulk_kyc_action():
    user_ids = request.form.getlist('user_ids')
    action = request.form.get('action')
    current_id = _current_user_id()
    
    users = User.query.filter(User.id.in_(user_ids)).all()
    
    if action == 'approve':
        for user in users:
            user.kyc_status = 'approved'
            user.kyc_notes = ''
            create_notification(user.id, 'KYC Verified', 'Congratulations! Your KYC has been successfully verified.', 'kyc', action_url='/challenges', icon='check', admin_id=current_id, dedupe_key=f'kyc-approved:{user.id}')
        db.session.commit()
        _log_if_moderator('kyc', 'bulk_approved_kyc', f'Bulk approved {len(users)} KYC applications', 'kyc_batch', None, None, {'count': len(users)})
        from email_service import send_automation_email
        for user in users:
            send_automation_email('kyc_approved', user)
        flash(f'Approved {len(users)} KYC applications.', 'success')
    elif action == 'reject':
        for user in users:
            user.kyc_status = 'rejected'
            user.kyc_notes = 'Bulk rejection'
        db.session.commit()
        _log_if_moderator('kyc', 'bulk_rejected_kyc', f'Bulk rejected {len(users)} KYC applications', 'kyc_batch', None, None, {'count': len(users)})
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
        _log_if_moderator('kyc', 'bulk_cleared_kyc', f'Bulk cleared {len(users)} KYC applications', 'kyc_batch', None, None, {'count': len(users)})
        flash(f'Cleared {len(users)} KYC applications.', 'success')
    
    return redirect(url_for('admin.admin_kyc'))


@admin_bp.route('/ban_user/<int:user_id>')
@admin_required
def admin_ban_user(user_id):
    user = User.query.get(user_id)
    if user and not user.is_admin:
        before_state = {'is_banned': user.is_banned}
        user.is_banned = True
        db.session.commit()
        _log_if_moderator('users', 'banned_user', f'Banned user {user.email}', 'user', user.id, before_state, {'is_banned': True})
        flash(f'User {user.email} has been banned.', 'success')
    else:
        flash('Cannot ban admin users.', 'error')
    return redirect(request.referrer or url_for('admin.admin_users'))


@admin_bp.route('/unban_user/<int:user_id>')
@admin_required
def admin_unban_user(user_id):
    user = User.query.get(user_id)
    if user and not user.is_admin:
        before_state = {'is_banned': user.is_banned}
        user.is_banned = False
        db.session.commit()
        _log_if_moderator('users', 'unbanned_user', f'Unbanned user {user.email}', 'user', user.id, before_state, {'is_banned': False})
        flash(f'User {user.email} has been unbanned.', 'success')
    else:
        flash('Cannot modify admin users.', 'error')
    return redirect(request.referrer or url_for('admin.admin_users'))


@admin_bp.route('/verify_phone/<int:user_id>')
@admin_required
def admin_verify_phone(user_id):
    user = User.query.get_or_404(user_id)
    before_state = {'phone_verified': user.phone_verified}
    user.phone_verified = True
    user.phone_verification_code = None
    db.session.commit()
    _log_if_moderator('users', 'verified_phone', f'Verified phone for {user.email}', 'user', user.id, before_state, {'phone_verified': True})
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
        _log_if_moderator('users', 'bulk_banned', f'Bulk banned {len(users)} users', 'users_batch', None, None, {'count': len(users)})
        flash(f'Banned {len(users)} users.', 'success')
    elif action == 'unban':
        for user in users:
            user.is_banned = False
        db.session.commit()
        _log_if_moderator('users', 'bulk_unbanned', f'Bulk unbanned {len(users)} users', 'users_batch', None, None, {'count': len(users)})
        flash(f'Unbanned {len(users)} users.', 'success')
    elif action == 'delete':
        for user in users:
            db.session.delete(user)
        db.session.commit()
        _log_if_moderator('users', 'bulk_deleted', f'Bulk deleted {len(users)} users', 'users_batch', None, None, {'count': len(users)})
        flash(f'Deleted {len(users)} users.', 'success')
    
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/api/users')
@admin_required
def api_users():
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except (ValueError, TypeError):
        page = 1
    
    try:
        per_page = min(max(int(request.args.get('per_page', 25)), 10), 100)
    except (ValueError, TypeError):
        per_page = 25
        
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
            'id': u.id, 'first_name': u.first_name, 'last_name': u.last_name,
            'email': u.email, 'phone': u.phone or 'N/A',
            'city': getattr(u, 'city', 'N/A'), 'state': getattr(u, 'state', 'N/A'),
            'country': getattr(u, 'country', 'N/A'),
            'status': 'banned' if u.is_banned else 'active',
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'kyc_status': getattr(u, 'kyc_status', 'N/A'),
        })
    return jsonify({
        'success': True, 'users': users_data,
        'total': pagination.total, 'pages': pagination.pages, 'current_page': pagination.page,
    })


@admin_bp.route('/user/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    user = User.query.get(user_id)
    if not user:
        abort(404)
    from email_service import get_or_create_preferences
    from models import EmailTemplate
    challenges = getattr(user, 'challenge_purchases', []) if hasattr(user, 'challenge_purchases') else []
    payments = getattr(user, 'payments', []) if hasattr(user, 'payments') else []
    support_tickets = getattr(user, 'support_tickets', []) if hasattr(user, 'support_tickets') else []
    payouts = getattr(user, 'payouts', []) if hasattr(user, 'payouts') else []
    email_templates = EmailTemplate.query.filter_by(is_active=True).order_by(EmailTemplate.name).all()
    email_preference = get_or_create_preferences(user.id)
    
    total_spent = sum(p.amount for p in payments if p.status.upper() == 'SUCCESS')
    total_purchases = len([p for p in payments if p.status.upper() == 'SUCCESS'])
    total_payouts = sum(p.amount for p in payouts if p.status.upper() == 'SUCCESS' or p.status.upper() == 'PAID')
    
    referrals = []
    return render_template('admin/user_detail.html', user=user,
                           challenges=challenges, payments=payments,
                           support_tickets=support_tickets, referrals=referrals,
                           total_spent=total_spent, total_purchases=total_purchases,
                           total_payouts=total_payouts,
                           email_templates=email_templates, email_preference=email_preference)


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
    active_challenges = ChallengePurchase.query.filter(ChallengePurchase.status.in_(['active', 'funded'])).count()
    passed_phase1 = ChallengePurchase.query.filter_by(status='passed', current_phase=1).count()
    passed_phase2 = ChallengePurchase.query.filter_by(status='passed', current_phase=2).count()
    funded_accounts = ChallengePurchase.query.filter_by(status='funded').count()
    failed_accounts = ChallengePurchase.query.filter(ChallengePurchase.status.in_(['failed', 'breached'])).count()
    pending_phase2_requests = ProgressionRequest.query.filter_by(request_type='phase2', status='pending').count()
    pending_funded_requests = ProgressionRequest.query.filter_by(request_type='funded', status='pending').count()
    approved_requests = ProgressionRequest.query.filter_by(status='approved').count()
    declined_requests = ProgressionRequest.query.filter_by(status='declined').count()
    expiring_soon = ChallengePurchase.query.filter(
        ChallengePurchase.status.in_(['active', 'funded']),
        ChallengePurchase.end_date <= expiring_threshold, ChallengePurchase.end_date >= now_utc
    ).count()
    pending_payouts = db.session.query(db.func.sum(Payout.amount)).filter(Payout.status == 'pending').scalar() or 0
    payout_eligible = Payout.query.filter_by(status='pending').count()
    
    return {
        'total_revenue': total_revenue, 'total_purchases': total_purchases,
        'today_purchases': today_purchases, 'pending_payouts': pending_payouts,
        'active_challenges': active_challenges, 'passed_phase1': passed_phase1,
        'passed_phase2': passed_phase2, 'funded_accounts': funded_accounts,
        'failed_accounts': failed_accounts, 'pending_phase2_requests': pending_phase2_requests,
        'pending_funded_requests': pending_funded_requests, 'approved_requests': approved_requests,
        'declined_requests': declined_requests, 'expiring_soon': expiring_soon,
        'payout_eligible': payout_eligible
    }


@admin_bp.route('/user/<int:user_id>/reset-password', methods=['POST'])
def admin_reset_user_password(user_id):
    from werkzeug.security import generate_password_hash
    user = User.query.get_or_404(user_id)
    new_password = ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(12))
    user.set_password(new_password)
    db.session.commit()
    _log_if_moderator('users', 'reset_password', f'Reset password for {user.email}', 'user', user.id)
    flash(f'Password reset to: {new_password}', 'success')
    return redirect(url_for('admin.admin_user_detail', user_id=user_id))


@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    user_email = user.email
    db.session.delete(user)
    db.session.commit()
    _log_if_moderator('users', 'deleted_user', f'Deleted user {user_email}', 'user', user_id)
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/user/<int:user_id>/analytics')
@admin_required
def admin_user_analytics(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/admin_user_analytics.html', user_id=user_id, user_name=user.get_full_name())


@admin_bp.route('/partner/<int:partner_id>/ban', methods=['POST'])
@admin_required
def ban_partner(partner_id):
    partner = User.query.get_or_404(partner_id)
    if partner.role != 'partner':
        flash('User is not a partner', 'error')
        return redirect(url_for('admin.partners'))
    partner.is_banned = True
    log = AdminLog(admin_id=_current_user_id(), action='ban_partner', target_type='partner', target_id=partner.id, details=f'Partner {partner.email} banned', ip_address=request.remote_addr)
    db.session.add(log)
    db.session.commit()
    _log_if_moderator('partners', 'banned_partner', f'Banned partner {partner.email}', 'partner', partner.id)
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
    log = AdminLog(admin_id=_current_user_id(), action='unban_partner', target_type='partner', target_id=partner.id, details=f'Partner {partner.email} unbanned', ip_address=request.remote_addr)
    db.session.add(log)
    db.session.commit()
    _log_if_moderator('partners', 'unbanned_partner', f'Unbanned partner {partner.email}', 'partner', partner.id)
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
    log = AdminLog(admin_id=_current_user_id(), action='revoke_partner', target_type='partner', target_id=partner.id, details=f'Partner access fully revoked for {partner.email}', ip_address=request.remote_addr)
    db.session.add(log)
    db.session.commit()
    _log_if_moderator('partners', 'revoked_partner', f'Revoked partner {partner.email}', 'partner', partner.id)
    flash(f'Partner access fully revoked for {partner.email}', 'success')
    return redirect(url_for('admin.partners'))


@admin_bp.route('/partners')
@admin_required
def partners():
    from models import PartnerEarnings
    all_partners = User.query.filter_by(role='partner').all()
    partner_stats = {}
    for p in all_partners:
        total_earned = db.session.query(func.sum(PartnerEarnings.partner_share)).filter_by(partner_id=p.id).scalar() or 0.0
        sales_count = PartnerEarnings.query.filter_by(partner_id=p.id).count()
        partner_stats[p.id] = {'total_earned': total_earned, 'sales_count': sales_count}
    return render_template('admin/partners.html', partners=all_partners, stats=partner_stats)


@admin_bp.route('/partner/create', methods=['POST'])
@admin_required
def create_partner():
    from werkzeug.security import generate_password_hash
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
        first_name=first_name, last_name=last_name, email=email,
        phone='', dob=datetime.now(timezone.utc).date(), country='N/A',
        password=generate_password_hash(password), role='partner', is_admin=False
    )
    db.session.add(new_partner)
    log = AdminLog(admin_id=_current_user_id(), action='create_partner', target_type='partner', target_id=0, details=f'Created new partner {email}', ip_address=request.remote_addr)
    db.session.add(log)
    db.session.commit()
    _log_if_moderator('partners', 'created_partner', f'Created partner {email}', 'partner', new_partner.id)
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
    from models import PartnerEarnings
    earning = PartnerEarnings.query.get_or_404(earning_id)
    earning.is_hidden = not earning.is_hidden
    log = AdminLog(admin_id=_current_user_id(), action='toggle_hide_earning', target_type='partner_earning', target_id=earning.id, details=f'Toggled hide state for earning {earning.id}', ip_address=request.remote_addr)
    db.session.add(log)
    db.session.commit()
    _log_if_moderator('partners', 'toggled_earning_visibility', f'Toggled earning #{earning.id}', 'partner_earning', earning.id)
    flash(f'Earning visibility updated successfully', 'success')
    return redirect(url_for('admin.partner_earnings', partner_id=earning.partner_id))


# ========================================================================
# LEAD CRM ROUTES - WITH FULL MODERATOR ACTIVITY LOGGING
# ========================================================================

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
        _log_if_moderator('lead_crm', 'created_status', f'Created lead status: {name}', 'lead_status', status.id)
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
        before = status.name
        status.name = name
        status.color = data.get('color') or status.color
        db.session.commit()
        _log_if_moderator('lead_crm', 'edited_status', f'Renamed status "{before}" to "{name}"', 'lead_status', status.id, {'name': before}, {'name': name})
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
        status_name = status.name
        User.query.filter_by(lead_status_id=status_id).update({'lead_status_id': None})
        db.session.delete(status)
        db.session.commit()
        _log_if_moderator('lead_crm', 'deleted_status', f'Deleted lead status: {status_name}', 'lead_status', status_id)
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
            query = query.filter(or_(User.first_name.ilike(like), User.last_name.ilike(like), User.email.ilike(like), User.phone.ilike(like)))

        query = query.order_by(User.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        leads_out = [{
            'id': u.id, 'name': u.get_full_name(), 'email': u.email, 'phone': u.phone,
            'status_name': u.lead_status.name if u.lead_status else None,
            'status_color': u.lead_status.color if u.lead_status else None,
            'kyc_status': u.kyc_status
        } for u in pagination.items]

        return jsonify({'success': True, 'leads': leads_out, 'total': pagination.total, 'pages': pagination.pages or 1, 'page': page})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/leads/api/<int:lead_id>/status', methods=['POST'])
@admin_required
def leads_api_change_status(lead_id):
    try:
        user = User.query.get_or_404(lead_id)
        data = request.get_json()
        old_status = user.lead_status.name if user.lead_status else 'None'
        user.lead_status_id = data.get('status_id')
        user.last_contacted_at = datetime.now(timezone.utc)
        db.session.commit()
        new_status = user.lead_status.name if user.lead_status else 'None'
        _log_if_moderator('lead_crm', 'changed_lead_status', f'Changed lead {user.email} status: {old_status} → {new_status}', 'lead', user.id, {'status': old_status}, {'status': new_status})
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
            current_id = _current_user_id()
            if not current_id:
                return jsonify({'success': False, 'error': 'Session expired. Please login again.'})
            note = LeadNote(user_id=lead_id, admin_id=current_id, content=content)
            db.session.add(note)
            db.session.commit()
            _log_if_moderator('lead_crm', 'added_note', f'Added note to lead #{lead_id}: {content[:80]}', 'lead', lead_id, None, {'note': content[:100]})
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
        lead_id = note.user_id
        db.session.delete(note)
        db.session.commit()
        _log_if_moderator('lead_crm', 'deleted_note', f'Deleted note #{note_id} from lead #{lead_id}', 'lead_note', note_id)
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
            current_id = _current_user_id()
            if not current_id:
                return jsonify({'success': False, 'error': 'Session expired. Please login again.'})
            followup = FollowUp(
                user_id=lead_id, admin_id=current_id,
                followup_date=datetime.fromisoformat(followup_date_str),
                followup_type=data.get('followup_type', 'Call'),
                notes=data.get('notes', '')
            )
            db.session.add(followup)
            db.session.commit()
            _log_if_moderator('lead_crm', 'scheduled_followup', f'Scheduled {followup.followup_type} follow-up for lead #{lead_id}', 'lead', lead_id, None, {'followup_date': followup_date_str, 'type': followup.followup_type})
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
        _log_if_moderator('lead_crm', 'completed_followup', f'Completed follow-up #{followup_id} for lead #{followup.user_id}', 'followup', followup_id)
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
            User.query.filter(User.id.in_(lead_ids)).update({'lead_status_id': data.get('status_id')}, synchronize_session=False)
            db.session.commit()
            _log_if_moderator('lead_crm', 'bulk_move_status', f'Bulk moved {len(lead_ids)} leads to new status', 'leads_batch', None, None, {'count': len(lead_ids)})
            return jsonify({'success': True})
        elif action == 'add_note':
            note_content = (data.get('note') or '').strip()
            if not note_content:
                return jsonify({'success': False, 'error': 'Note content is required'})
            current_id = _current_user_id()
            if not current_id:
                return jsonify({'success': False, 'error': 'Session expired. Please login again.'})
            for uid in lead_ids:
                db.session.add(LeadNote(user_id=uid, admin_id=current_id, content=note_content))
            db.session.commit()
            _log_if_moderator('lead_crm', 'bulk_add_note', f'Bulk added note to {len(lead_ids)} leads', 'leads_batch', None, None, {'count': len(lead_ids), 'note': note_content[:100]})
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Unknown action'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})