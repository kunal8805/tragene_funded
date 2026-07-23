from flask import render_template, request, redirect, url_for, flash, session, jsonify, Response
from datetime import datetime, timedelta, timezone
from models import db, User, Moderator, ModeratorActivityLog, MODERATOR_PERMISSIONS, RESTRICTED_PERMISSIONS, SupportTicket, ChallengePurchase
from . import admin_bp, admin_required, get_current_moderator, log_moderator_activity, validate_permissions
from sqlalchemy import func
import secrets
import re
import csv
import io

# ========================================================================
# VALIDATION HELPERS
# ========================================================================

def is_valid_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def is_strong_password(password):
    """Enforce password strength policy"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-]', password):
        return False, "Password must contain at least one special character"
    return True, ""

def get_client_ip():
    """Safely get client IP address"""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        ip = forwarded.split(',')[0].strip()
    else:
        ip = request.remote_addr or 'unknown'
    return ip[:45]


# ========================================================================
# SUPER ADMIN ONLY - MANAGE MODERATORS
# ========================================================================

@admin_bp.route('/moderators')
@admin_required
def manage_moderators():
    """List all moderators with stats"""
    
    total_moderators = Moderator.query.count()
    active_moderators = Moderator.query.filter_by(status='active').count()
    
    now = datetime.now(timezone.utc)
    banned_moderators = Moderator.query.filter(
        Moderator.status == 'temp_banned',
        Moderator.ban_until > now
    ).count()
    
    inactive_moderators = Moderator.query.filter_by(status='inactive').count()
    
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_actions = ModeratorActivityLog.query.filter(
        ModeratorActivityLog.created_at >= today_start
    ).count()
    
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_actions = ModeratorActivityLog.query.filter(
        ModeratorActivityLog.created_at >= month_start
    ).count()
    
    moderators = Moderator.query.order_by(Moderator.created_at.desc()).all()
    
    for mod in moderators:
        mod.permissions_count = len(mod.get_active_permissions())
    
    stats = {
        'total': total_moderators,
        'active': active_moderators,
        'banned': banned_moderators,
        'inactive': inactive_moderators,
        'today_actions': today_actions,
        'month_actions': month_actions
    }
    
    return render_template('admin/moderator/moderator.html', 
                         mode='list',
                         moderators=moderators,
                         stats=stats,
                         permissions=MODERATOR_PERMISSIONS)


@admin_bp.route('/moderators/add', methods=['GET', 'POST'])
@admin_required
def add_moderator():
    """Add new moderator with permissions"""
    
    if request.method == 'POST':
        try:
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            status = request.form.get('status', 'active')
            
            errors = []
            if not full_name or len(full_name) < 2:
                errors.append("Full name must be at least 2 characters")
            if len(full_name) > 100:
                errors.append("Full name must be less than 100 characters")
            if not email or not is_valid_email(email):
                errors.append("Valid email is required")
            if not password:
                errors.append("Password is required")
            if password != confirm_password:
                errors.append("Passwords do not match")
            
            is_strong, strength_msg = is_strong_password(password)
            if not is_strong:
                errors.append(strength_msg)
            
            if status not in ['active', 'inactive']:
                errors.append("Invalid status selection")
            
            if Moderator.query.filter_by(email=email).first():
                errors.append("A moderator with this email already exists")
            
            if User.query.filter_by(email=email).first():
                errors.append("This email is already registered as a platform user")
            
            if errors:
                for error in errors:
                    flash(error, 'error')
                return render_template('admin/moderator/moderator.html',
                                     mode='add',
                                     permissions=MODERATOR_PERMISSIONS,
                                     form_data=request.form)
            
            raw_permissions = {}
            for key in MODERATOR_PERMISSIONS:
                raw_permissions[key] = request.form.get(f'perm_{key}') == 'on'
            
            validated_permissions = validate_permissions(raw_permissions)
            
            moderator = Moderator(
                full_name=full_name,
                email=email,
                status=status,
                permissions=validated_permissions,
                created_by_admin_id=session.get('user_id', 1)
            )
            moderator.set_password(password)
            
            db.session.add(moderator)
            db.session.flush()
            
            log_moderator_activity(
                moderator_id=moderator.id,
                module='moderator_management',
                action='moderator_created',
                description=f'Created by super admin',
                target_type='moderator',
                target_id=moderator.id,
                after_state={
                    'full_name': full_name,
                    'email': email,
                    'status': status,
                    'permissions': validated_permissions
                },
                status='success'
            )
            
            db.session.commit()
            flash(f'Moderator "{full_name}" created successfully!', 'success')
            return redirect(url_for('admin.manage_moderators'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating moderator. Please try again.', 'error')
            return redirect(url_for('admin.add_moderator'))
    
    return render_template('admin/moderator/moderator.html',
                         mode='add',
                         permissions=MODERATOR_PERMISSIONS)


@admin_bp.route('/moderators/<int:moderator_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_moderator(moderator_id):
    """Edit moderator permissions"""
    moderator = Moderator.query.get_or_404(moderator_id)
    
    if request.method == 'POST':
        try:
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            status = request.form.get('status', 'active')
            new_password = request.form.get('password', '')
            
            errors = []
            if not full_name or len(full_name) < 2:
                errors.append("Full name must be at least 2 characters")
            if not email or not is_valid_email(email):
                errors.append("Valid email is required")
            
            existing = Moderator.query.filter(
                Moderator.email == email,
                Moderator.id != moderator_id
            ).first()
            if existing:
                errors.append("Another moderator with this email already exists")
            
            if status not in ['active', 'inactive']:
                errors.append("Invalid status")
            
            if new_password:
                is_strong, strength_msg = is_strong_password(new_password)
                if not is_strong:
                    errors.append(strength_msg)
            
            if errors:
                for error in errors:
                    flash(error, 'error')
                return render_template('admin/moderator/moderator.html',
                                     mode='edit',
                                     moderator=moderator,
                                     permissions=MODERATOR_PERMISSIONS)
            
            before_state = {
                'full_name': moderator.full_name,
                'email': moderator.email,
                'status': moderator.status,
                'permissions': moderator.permissions
            }
            
            moderator.full_name = full_name
            moderator.email = email
            moderator.status = status
            
            if new_password:
                moderator.set_password(new_password)
            
            raw_permissions = {}
            for key in MODERATOR_PERMISSIONS:
                raw_permissions[key] = request.form.get(f'perm_{key}') == 'on'
            
            moderator.permissions = validate_permissions(raw_permissions)
            
            after_state = {
                'full_name': moderator.full_name,
                'email': moderator.email,
                'status': moderator.status,
                'permissions': moderator.permissions
            }
            
            log_moderator_activity(
                moderator_id=moderator.id,
                module='moderator_management',
                action='moderator_updated',
                description=f'Updated by super admin',
                target_type='moderator',
                target_id=moderator.id,
                before_state=before_state,
                after_state=after_state,
                status='success'
            )
            
            db.session.commit()
            flash(f'Moderator "{full_name}" updated successfully!', 'success')
            return redirect(url_for('admin.manage_moderators'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating moderator. Please try again.', 'error')
            return redirect(url_for('admin.edit_moderator', moderator_id=moderator_id))
    
    return render_template('admin/moderator/moderator.html',
                         mode='edit',
                         moderator=moderator,
                         permissions=MODERATOR_PERMISSIONS)


@admin_bp.route('/moderators/<int:moderator_id>/ban', methods=['POST'])
@admin_required
def ban_moderator(moderator_id):
    """Temporary ban moderator"""
    moderator = Moderator.query.get_or_404(moderator_id)
    
    duration = request.form.get('duration', '7')
    custom_days = request.form.get('custom_days', '')
    reason = request.form.get('reason', '').strip()[:500]
    
    valid_durations = {'1': 1, '3': 3, '7': 7, '30': 30}
    
    if duration == 'custom':
        if not custom_days.isdigit():
            flash('Custom days must be a number', 'error')
            return redirect(url_for('admin.manage_moderators'))
        days = int(custom_days)
        if days < 1 or days > 365:
            flash('Custom ban duration must be between 1 and 365 days', 'error')
            return redirect(url_for('admin.manage_moderators'))
    elif duration in valid_durations:
        days = valid_durations[duration]
    else:
        flash('Invalid ban duration', 'error')
        return redirect(url_for('admin.manage_moderators'))
    
    before_state = {
        'status': moderator.status,
        'ban_until': moderator.ban_until.isoformat() if moderator.ban_until else None
    }
    
    moderator.status = 'temp_banned'
    moderator.ban_until = datetime.now(timezone.utc) + timedelta(days=days)
    moderator.ban_reason = reason
    
    after_state = {
        'status': moderator.status,
        'ban_until': moderator.ban_until.isoformat(),
        'ban_duration_days': days,
        'ban_reason': reason
    }
    
    log_moderator_activity(
        moderator_id=moderator.id,
        module='moderator_management',
        action='moderator_banned',
        description=f'Banned for {days} days. Reason: {reason or "Not specified"}',
        target_type='moderator',
        target_id=moderator.id,
        before_state=before_state,
        after_state=after_state,
        status='success'
    )
    
    db.session.commit()
    flash(f'Moderator "{moderator.full_name}" banned for {days} days', 'success')
    return redirect(url_for('admin.manage_moderators'))


@admin_bp.route('/moderators/<int:moderator_id>/activate', methods=['POST'])
@admin_required
def activate_moderator(moderator_id):
    """Activate or deactivate moderator"""
    moderator = Moderator.query.get_or_404(moderator_id)
    
    action = request.form.get('action', 'activate')
    
    before_state = {
        'status': moderator.status,
        'ban_until': moderator.ban_until.isoformat() if moderator.ban_until else None
    }
    
    if action == 'activate':
        moderator.status = 'active'
        moderator.ban_until = None
        moderator.ban_reason = None
        flash(f'Moderator "{moderator.full_name}" activated', 'success')
        log_action = 'moderator_activated'
    elif action == 'deactivate':
        moderator.status = 'inactive'
        flash(f'Moderator "{moderator.full_name}" deactivated', 'success')
        log_action = 'moderator_deactivated'
    else:
        flash('Invalid action', 'error')
        return redirect(url_for('admin.manage_moderators'))
    
    after_state = {
        'status': moderator.status,
        'ban_until': moderator.ban_until.isoformat() if moderator.ban_until else None
    }
    
    log_moderator_activity(
        moderator_id=moderator.id,
        module='moderator_management',
        action=log_action,
        target_type='moderator',
        target_id=moderator.id,
        before_state=before_state,
        after_state=after_state,
        status='success'
    )
    
    db.session.commit()
    return redirect(url_for('admin.manage_moderators'))


@admin_bp.route('/moderators/<int:moderator_id>/delete', methods=['POST'])
@admin_required
def delete_moderator(moderator_id):
    """Delete moderator (activity logs preserved)"""
    moderator = Moderator.query.get_or_404(moderator_id)
    
    activity_count = ModeratorActivityLog.query.filter_by(moderator_id=moderator.id).count()
    moderator_name = moderator.full_name
    moderator_email = moderator.email
    
    from models import AdminLog
    log = AdminLog(
        admin_id=session.get('user_id', 1),
        action='delete_moderator',
        target_type='moderator',
        target_id=moderator_id,
        details=f'Deleted moderator {moderator_name} ({moderator_email}). {activity_count} activity logs preserved.',
        ip_address=get_client_ip()
    )
    db.session.add(log)
    
    db.session.delete(moderator)
    db.session.commit()
    
    flash(f'Moderator "{moderator_name}" deleted. {activity_count} activity logs preserved for audit.', 'success')
    return redirect(url_for('admin.manage_moderators'))


@admin_bp.route('/moderators/<int:moderator_id>/reset-password', methods=['POST'])
@admin_required
def reset_moderator_password(moderator_id):
    """Reset moderator password"""
    moderator = Moderator.query.get_or_404(moderator_id)
    
    new_password = secrets.token_urlsafe(16)
    moderator.set_password(new_password)
    
    log_moderator_activity(
        moderator_id=moderator.id,
        module='moderator_management',
        action='password_reset',
        description='Password reset by super admin',
        target_type='moderator',
        target_id=moderator.id,
        status='success'
    )
    
    db.session.commit()
    
    flash(f'Password for "{moderator.full_name}" has been reset.', 'success')
    flash(f'New temporary password: <code class="bg-gray-200 dark:bg-gray-700 px-2 py-1 rounded">{new_password}</code> (share securely)', 'info')
    return redirect(url_for('admin.manage_moderators'))


# ========================================================================
# ACTIVITY LOG VIEWER - WITH FULL BREAKDOWN ANALYTICS
# ========================================================================

@admin_bp.route('/moderators/activity')
@admin_required
def moderator_activity():
    """Complete forensic activity log viewer with analytics"""
    
    moderator_filter = request.args.get('moderator_id', 'all')
    module_filter = request.args.get('module', 'all')
    action_filter = request.args.get('action', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    status_filter = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)
    
    query = ModeratorActivityLog.query
    
    if moderator_filter != 'all' and moderator_filter.isdigit():
        query = query.filter_by(moderator_id=int(moderator_filter))
    if module_filter != 'all':
        query = query.filter_by(module=module_filter)
    if action_filter != 'all':
        query = query.filter(ModeratorActivityLog.action.ilike(f'%{action_filter}%'))
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    if date_from:
        try:
            query = query.filter(ModeratorActivityLog.created_at >= datetime.fromisoformat(date_from))
        except:
            pass
    if date_to:
        try:
            query = query.filter(ModeratorActivityLog.created_at <= datetime.fromisoformat(date_to) + timedelta(days=1))
        except:
            pass
    
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # ========================================================================
    # BASIC STATS
    # ========================================================================
    stats = {
        'today': ModeratorActivityLog.query.filter(ModeratorActivityLog.created_at >= today_start).count(),
        'weekly': ModeratorActivityLog.query.filter(ModeratorActivityLog.created_at >= week_start).count(),
        'monthly': ModeratorActivityLog.query.filter(ModeratorActivityLog.created_at >= month_start).count(),
        'total': ModeratorActivityLog.query.count(),
        'unique_modules': db.session.query(func.count(func.distinct(ModeratorActivityLog.module))).scalar() or 0,
    }
    
    # Most active moderator
    most_active = db.session.query(
        Moderator.full_name,
        func.count(ModeratorActivityLog.id).label('count')
    ).join(ModeratorActivityLog, ModeratorActivityLog.moderator_id == Moderator.id)\
     .group_by(Moderator.id).order_by(func.count(ModeratorActivityLog.id).desc()).first()
    
    stats['most_active'] = most_active[0] if most_active else 'N/A'
    stats['most_active_count'] = most_active[1] if most_active else 0
    
    # ========================================================================
    # ACTION BREAKDOWN STATS
    # ========================================================================
    stats['kyc_actions'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'kyc').count()
    stats['kyc_approved'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'kyc', ModeratorActivityLog.action == 'approved_kyc').count()
    stats['kyc_rejected'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'kyc', ModeratorActivityLog.action == 'rejected_kyc').count()
    stats['kyc_cleared'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'kyc', ModeratorActivityLog.action == 'cleared_kyc').count()

    stats['lead_actions'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'lead_crm').count()
    stats['lead_notes'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'lead_crm', ModeratorActivityLog.action == 'added_note').count()
    stats['lead_status_changes'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'lead_crm', ModeratorActivityLog.action == 'changed_lead_status').count()
    stats['lead_followups'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'lead_crm', ModeratorActivityLog.action.in_(['scheduled_followup', 'completed_followup'])).count()

    stats['user_actions'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'users').count()
    stats['users_banned'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'users', ModeratorActivityLog.action.in_(['banned_user', 'bulk_banned'])).count()
    stats['users_unbanned'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'users', ModeratorActivityLog.action.in_(['unbanned_user', 'bulk_unbanned'])).count()
    stats['password_resets'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'users', ModeratorActivityLog.action == 'reset_password').count()

    stats['blog_actions'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'blog').count()
    stats['notification_actions'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'notifications').count()
    stats['partner_actions'] = ModeratorActivityLog.query.filter(ModeratorActivityLog.module == 'partners').count()
    stats['other_actions'] = stats['total'] - stats['kyc_actions'] - stats['lead_actions'] - stats['user_actions'] - stats['blog_actions'] - stats['notification_actions'] - stats['partner_actions']
    if stats['other_actions'] < 0:
        stats['other_actions'] = 0

    # ========================================================================
    # TODAY BY MODERATOR
    # ========================================================================
    today_by_mod = db.session.query(
        Moderator.full_name, 
        func.count(ModeratorActivityLog.id).label('count')
    ).join(ModeratorActivityLog)\
     .filter(ModeratorActivityLog.created_at >= today_start)\
     .group_by(Moderator.id)\
     .order_by(func.count(ModeratorActivityLog.id).desc()).limit(5).all()
    
    stats['today_by_moderator'] = {m.full_name: m.count for m in today_by_mod} if today_by_mod else {'No activity': 0}

    # ========================================================================
    # LAST 7 DAYS BREAKDOWN
    # ========================================================================
    last_7 = {}
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).strftime('%a')
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = ModeratorActivityLog.query.filter(
            ModeratorActivityLog.created_at >= day_start, 
            ModeratorActivityLog.created_at < day_end
        ).count()
        last_7[day] = count
    stats['last_7_days'] = last_7
    stats['weekly_peak'] = max(last_7.values()) if last_7 else 1

    # ========================================================================
    # MONTHLY COMPARISON
    # ========================================================================
    last_month_start = (now.replace(day=1) - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    stats['last_month'] = ModeratorActivityLog.query.filter(
        ModeratorActivityLog.created_at >= last_month_start,
        ModeratorActivityLog.created_at < last_month_end
    ).count()

    # ========================================================================
    # PAGINATE LOGS
    # ========================================================================
    logs = query.order_by(ModeratorActivityLog.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    all_moderators = Moderator.query.order_by(Moderator.full_name).all()
    modules = [m[0] for m in db.session.query(ModeratorActivityLog.module).distinct().all()]
    
    return render_template('admin/moderator/activity.html',
                         logs=logs, stats=stats,
                         moderators=all_moderators, modules=modules,
                         filters={
                             'moderator_id': moderator_filter,
                             'module': module_filter,
                             'action': action_filter,
                             'date_from': date_from,
                             'date_to': date_to,
                             'status': status_filter
                         })


@admin_bp.route('/moderators/activity/export')
@admin_required
def export_activity_csv():
    """Export activity logs as CSV"""
    moderator_filter = request.args.get('moderator_id', 'all')
    module_filter = request.args.get('module', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    query = ModeratorActivityLog.query
    if moderator_filter != 'all' and moderator_filter.isdigit():
        query = query.filter_by(moderator_id=int(moderator_filter))
    if module_filter != 'all':
        query = query.filter_by(module=module_filter)
    if date_from:
        try:
            query = query.filter(ModeratorActivityLog.created_at >= datetime.fromisoformat(date_from))
        except:
            pass
    if date_to:
        try:
            query = query.filter(ModeratorActivityLog.created_at <= datetime.fromisoformat(date_to) + timedelta(days=1))
        except:
            pass
    
    logs = query.order_by(ModeratorActivityLog.created_at.desc()).limit(10000).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Timestamp', 'Moderator', 'Module', 'Action', 'Description', 
                     'Target Type', 'Target ID', 'IP Address', 'Status'])
    
    for log in logs:
        writer.writerow([
            log.id,
            log.created_at.isoformat() if log.created_at else '',
            log.moderator.full_name if log.moderator else 'Unknown',
            log.module, log.action, log.description or '',
            log.target_type or '', log.target_id or '',
            log.ip_address or '', log.status
        ])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename=moderator_activity_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'})


@admin_bp.route('/api/moderators/activity/<int:log_id>')
@admin_required
def get_activity_detail(log_id):
    """API endpoint for activity log detail"""
    log = ModeratorActivityLog.query.get_or_404(log_id)
    return jsonify({'success': True, 'log': log.to_dict()})


# ========================================================================
# MODERATOR DASHBOARD
# ========================================================================

@admin_bp.route('/moderator/dashboard')
def moderator_dashboard():
    """Simple operational dashboard for moderators"""
    
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and user.is_admin:
            return redirect(url_for('admin.admin_dashboard'))
    
    moderator = get_current_moderator()
    if not moderator:
        session.pop('moderator_id', None)
        flash('Please login to access the dashboard.', 'error')
        return redirect(url_for('auth.login'))
    
    if not moderator.is_active():
        session.pop('moderator_id', None)
        flash('Your account is currently disabled. Contact admin.', 'error')
        return redirect(url_for('auth.login'))
    
    stats = {
        'assigned_modules': len(moderator.get_active_permissions()),
        'pending_kyc': 0,
        'open_tickets': 0,
        'active_challenges': 0,
        'blog_posts': 0,
    }
    
    if moderator.has_permission('can_access_kyc'):
        stats['pending_kyc'] = User.query.filter_by(kyc_status='submitted').count()
    if moderator.has_permission('can_access_support'):
        stats['open_tickets'] = SupportTicket.query.filter_by(status='open').count()
    if moderator.has_permission('can_access_challenges'):
        stats['active_challenges'] = ChallengePurchase.query.filter(
            ChallengePurchase.status.in_(['active', 'phase1_active', 'phase2_active', 'funded_active'])
        ).count()
    if moderator.has_permission('can_access_blog'):
        from models import BlogPost
        stats['blog_posts'] = BlogPost.query.count()
    
    recent_activity = ModeratorActivityLog.query.filter_by(
        moderator_id=moderator.id
    ).order_by(ModeratorActivityLog.created_at.desc()).limit(20).all()
    
    moderator.last_activity = datetime.now(timezone.utc)
    db.session.commit()
    
    return render_template('admin/moderator/dashboard.html',
                         moderator=moderator,
                         stats=stats,
                         recent_activity=recent_activity,
                         permissions_list=MODERATOR_PERMISSIONS)