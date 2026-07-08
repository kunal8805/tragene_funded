from flask import render_template, request, redirect, url_for, flash, session, jsonify, abort, Response, send_file
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, extract  # ADD THIS LINE
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, PayoutAuditLog, FAQ, SupportTicket, TicketMessage, Payment, AdminLog, Notification, UserNotification, NotificationTemplate, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection, PartnerEarnings  # ADD PartnerEarnings
from . import admin_bp, admin_required
from notification_service import notify_all_users  # ADD THIS if missing
import secrets
import csv
import io
import json

from . import _admin_name, _notify_user, _notify_challenge_passed, _notify_challenge_breached, _activate_progression_stage, _payout_audit, _eligible_funded_count, _payout_stats

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
        
        # ⚖️ Lot Size Rules
        challenge.max_lot_size_enabled = 'max_lot_size_enabled' in request.form
        challenge.max_lot_size = float(request.form.get('max_lot_size', 0.02) or 0.02)
        challenge.lot_size_violation_action = request.form.get('lot_size_violation_action', 'flag')
        
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



