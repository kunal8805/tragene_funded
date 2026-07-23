from flask import render_template, request, redirect, url_for, flash, session, jsonify, abort, Response, send_file
from datetime import datetime, timedelta, timezone
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, PayoutAuditLog, FAQ, SupportTicket, TicketMessage, Payment, AdminLog, Notification, UserNotification, NotificationTemplate, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection
from . import admin_bp, admin_required
from notification_service import create_notification
import secrets
import csv
import io
import json

from . import _admin_name, _notify_user, _notify_challenge_passed, _notify_challenge_breached, _activate_progression_stage, _payout_audit, _eligible_funded_count, _payout_stats

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


@admin_bp.route('/settings')
@admin_required
def admin_settings():
    return render_template('admin/settings.html')


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
        admin_id=session.get('user_id') or session.get('moderator_id')
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
