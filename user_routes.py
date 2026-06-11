from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
from models import db, User, ChallengeTemplate, ChallengePurchase, Payment, Payout, PayoutAuditLog, SupportTicket, TicketMessage, FAQ, RuleLog, TradeHistory, Notification, UserNotification, Coupon, CouponUsage, CouponAssignment, ProgressionRequest
from datetime import datetime, timezone, timedelta
import os
import secrets
import random
import json
from werkzeug.utils import secure_filename
from PIL import Image
import time

def compress_and_save_ticket_attachment(attachment, ticket_number, prefix=""):
    ext = attachment.filename.rsplit('.', 1)[1].lower() if '.' in attachment.filename else ''
    if ext not in {'png', 'jpg', 'jpeg', 'pdf'}:
        return None
        
    upload_dir = os.path.join('static', 'uploads', 'tickets')
    os.makedirs(upload_dir, exist_ok=True)
    
    if ext in {'png', 'jpg', 'jpeg'}:
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

user_bp = Blueprint('user', __name__, url_prefix='/user')

ACTIVE_PAYOUT_STATUSES = ['pending', 'under_review', 'approved']
ACTIVE_CHALLENGE_STATUSES = ['active', 'funded']
HISTORY_CHALLENGE_STATUSES = ['passed', 'failed', 'inactive']

def _cycle_days(cycle):
    cycle = (cycle or '').lower()
    if cycle in ['weekly', 'week', '7_days']:
        return 7
    if cycle in ['monthly', 'month']:
        return 30
    return 14

def _aware(dt):
    if not dt:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _payout_notification(user_id, title, message):
    _user_notification(user_id, title, message)

def _user_notification(user_id, title, message):
    notification = Notification(
        title=title,
        message=message,
        is_global=False,
        target_user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db.session.add(notification)
    db.session.flush()
    db.session.add(UserNotification(notification_id=notification.id, user_id=user_id))

def payout_account_type(challenge):
    if challenge.challenge_type == 'instant':
        return 'Instant Funding Account'
    if challenge.status in ['funded', 'funded_active']:
        return 'Funded Account'
    return (challenge.status or 'Challenge').replace('_', ' ').title()

def payout_eligibility(challenge):
    template = challenge.challenge_template
    account_size = float(template.account_size if template else challenge.starting_balance or challenge.current_balance or 0)
    profit_share = float(template.user_profit_share if template else 0)
    minimum = round(account_size * 0.05, 2)
    is_funded = challenge.status in ['funded', 'funded_active'] or challenge.challenge_type == 'instant'
    if not is_funded or challenge.status in ['active', 'passed', 'pending_phase2', 'pending_funded', 'phase1_active', 'phase2_active', 'failed', 'expired', 'revoked']:
        return {
            'eligible': False,
            'reason': 'Only Instant Funding Accounts and Funded Accounts can request payouts.',
            'account_size': account_size,
            'minimum': minimum,
            'available_profit': 0.0,
            'profit_share': profit_share,
            'next_date': None,
            'cycle_days': _cycle_days(template.payout_cycle if template else None),
            'account_type': payout_account_type(challenge)
        }

    funded_at = _aware(challenge.funded_at or challenge.start_date or challenge.purchase_date or challenge.created_at)
    cycle_days = _cycle_days(template.payout_cycle if template else None)
    cycle_start = funded_at or _aware(challenge.created_at) or datetime.now(timezone.utc)
    last_completed = Payout.query.filter(
        Payout.challenge_purchase_id == challenge.id,
        Payout.status == 'paid'
    ).order_by(Payout.updated_at.desc()).first()
    if last_completed:
        cycle_start = _aware(last_completed.paid_at or last_completed.updated_at or last_completed.created_at) or cycle_start
    next_date = cycle_start + timedelta(days=cycle_days)

    active_request = Payout.query.filter(
        Payout.challenge_purchase_id == challenge.id,
        Payout.status.in_(ACTIVE_PAYOUT_STATUSES)
    ).first()

    baseline = float(challenge.phase_start_balance or challenge.starting_balance or account_size or 0)
    current_value = float(challenge.current_equity or challenge.current_balance or baseline)
    funded_profit = max(0.0, current_value - baseline)
    paid_amount = db.session.query(db.func.coalesce(db.func.sum(Payout.amount), 0)).filter(
        Payout.challenge_purchase_id == challenge.id,
        Payout.status == 'paid'
    ).scalar() or 0
    available_profit = round(max(0.0, (funded_profit * (profit_share / 100.0)) - float(paid_amount)), 2)

    now = datetime.now(timezone.utc)
    eligible = True
    reason = ''
    if active_request:
        eligible = False
        reason = 'A payout request is already active for this account.'
    elif available_profit < minimum:
        eligible = False
        reason = 'Minimum payout threshold not reached.'
    elif now < next_date:
        eligible = False
        reason = f"Next payout date: {next_date.strftime('%d %B %Y')}"

    return {
        'eligible': eligible,
        'reason': reason,
        'account_size': account_size,
        'minimum': minimum,
        'available_profit': available_profit,
        'profit_share': profit_share,
        'next_date': next_date,
        'cycle_days': cycle_days,
        'account_type': payout_account_type(challenge),
        'active_request': active_request
    }

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# ===== DASHBOARD ROUTES =====
@user_bp.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    if not user_id:
        flash('Please login again.', 'error')
        return redirect(url_for('auth.login'))
    
    user = User.query.get(user_id)
    if not user:
        flash('User not found. Please login again.', 'error')
        session.clear()
        return redirect(url_for('auth.login'))
    
    # Get user's active challenges (compact, limited to 3)
    active_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(ACTIVE_CHALLENGE_STATUSES)
    ).order_by(ChallengePurchase.created_at.desc()).limit(3).all()
    
    # Calculate days remaining
    now_utc = datetime.now(timezone.utc)
    for challenge in active_challenges:
        if challenge.end_date:
            end_date = challenge.end_date.replace(tzinfo=timezone.utc) if challenge.end_date.tzinfo is None else challenge.end_date
            days_left = (end_date - now_utc).days
            challenge.days_remaining = max(0, days_left)
        else:
            challenge.days_remaining = 0
        
        if challenge.current_profit is None:
            challenge.current_profit = 0.0
        if challenge.progress_percentage is None:
            challenge.progress_percentage = 0.0
        if challenge.max_drawdown_used is None:
            challenge.max_drawdown_used = 0.0
    
    # Available challenges for purchase (limit 3)
    available_challenges = ChallengeTemplate.query.filter_by(is_active=True).order_by(ChallengeTemplate.price).limit(3).all()
    
    # Pending payouts count
    pending_payouts_count = Payout.query.filter(
        Payout.user_id == user.id,
        Payout.status.in_(ACTIVE_PAYOUT_STATUSES)
    ).count()
    
    # Open tickets
    open_tickets = SupportTicket.query.filter_by(user_id=user.id, status='open').order_by(SupportTicket.updated_at.desc()).limit(3).all()
    
    # Active coupons count
    now = datetime.now(timezone.utc)
    active_coupons = Coupon.query.filter_by(is_active=True, is_deleted=False).all()
    active_coupons_count = 0
    for coupon in active_coupons:
        if coupon.expires_at:
            expires_at = coupon.expires_at.replace(tzinfo=timezone.utc) if coupon.expires_at.tzinfo is None else coupon.expires_at
            if expires_at < now:
                continue
        used = CouponUsage.query.filter_by(coupon_id=coupon.id, user_id=user.id).first()
        if used:
            continue
        if coupon.coupon_type in ['universal', 'influencer']:
            if coupon.max_uses is None or coupon.used_count < coupon.max_uses:
                active_coupons_count += 1
        elif coupon.coupon_type == 'specific':
            assignment = CouponAssignment.query.filter_by(coupon_id=coupon.id, user_id=user.id, is_used=False).first()
            if assignment:
                active_coupons_count += 1
    
    all_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(HISTORY_CHALLENGE_STATUSES)
    ).order_by(ChallengePurchase.created_at.desc()).limit(5).all()
    progression_requests = ProgressionRequest.query.filter_by(user_id=user.id).order_by(ProgressionRequest.created_at.desc()).limit(5).all()
    progression_eligible_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status == 'passed',
        ChallengePurchase.current_phase.in_([1, 2])
    ).order_by(ChallengePurchase.completed_at.desc().nullslast()).all()
    
    return render_template('user/user_dashboard.html',
                         user=user, 
                         active_challenges=active_challenges,
                         available_challenges=available_challenges,
                         pending_payouts_count=pending_payouts_count,
                         open_tickets=open_tickets,
                         active_coupons_count=active_coupons_count,
                         all_challenges=all_challenges,
                         progression_requests=progression_requests,
                         progression_eligible_challenges=progression_eligible_challenges,
                         SupportTicket=SupportTicket)

@user_bp.route('/dashboard/stats')
@login_required
def dashboard_stats():
    """API endpoint for dashboard statistics"""
    user = User.query.get(session['user_id'])
    
    active_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(ACTIVE_CHALLENGE_STATUSES)
    ).all()
    
    total_balance = sum(c.current_balance or 0 for c in active_challenges)
    total_profit = sum(c.current_profit or 0 for c in active_challenges)
    
    stats = {
        'account_balance': total_balance,
        'current_profit': total_profit,
        'active_challenges_count': len(active_challenges),
        'drawdown_used': max([c.max_drawdown_used or 0 for c in active_challenges], default=0),
        'days_remaining': min([c.days_remaining or 30 for c in active_challenges], default=30),
    }
    
    return jsonify({'success': True, 'stats': stats})

# ===== KYC ROUTES =====
@user_bp.route('/kyc')
@login_required
def kyc():
    user = User.query.get(session['user_id'])
    return render_template('user/kyc_verify.html', user=user)

@user_bp.route('/kyc/verify', methods=['GET', 'POST'])
@login_required
def kyc_verification():
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        if not user.email_verified:
            flash('Please verify your email address first.', 'error')
            return redirect(url_for('user.kyc_verification'))

        document_type = request.form.get('document_type')
        document_number = request.form.get('document_number', '').strip()
        
        if document_type not in ['aadhaar', 'pan', 'driving_license']:
            flash('Please select a valid document type.', 'error')
            return redirect(url_for('user.kyc_verification'))
        
        if not document_number:
            flash('Please enter your document number.', 'error')
            return redirect(url_for('user.kyc_verification'))
        
        front_file = request.files.get('front_file')
        back_file = request.files.get('back_file')
        
        if not front_file or front_file.filename == '':
            flash('Please upload front side of your document.', 'error')
            return redirect(url_for('user.kyc_verification'))
        
        if not back_file or back_file.filename == '':
            flash('Please upload back side of your document.', 'error')
            return redirect(url_for('user.kyc_verification'))
        
        # Check file sizes before processing
        max_size = 16 * 1024 * 1024  # 16MB per file
        
        front_file.seek(0, 2)
        front_size = front_file.tell()
        front_file.seek(0)
        if front_size > max_size:
            flash('Your front document image is too large. Please reduce the size and try again.', 'warning')
            return redirect(url_for('user.file_too_large'))
        
        back_file.seek(0, 2)
        back_size = back_file.tell()
        back_file.seek(0)
        if back_size > max_size:
            flash('Your back document image is too large. Please reduce the size and try again.', 'warning')
            return redirect(url_for('user.file_too_large'))
        
        def allowed_file(filename):
            return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'pdf'}
        
        if not (allowed_file(front_file.filename) and allowed_file(back_file.filename)):
            flash('Only PNG, JPG, JPEG, and PDF files are allowed.', 'error')
            return redirect(url_for('user.kyc_verification'))
        
        def process_kyc_image(file_storage, prefix):
            ext = file_storage.filename.rsplit('.', 1)[1].lower()
            timestamp = int(time.time())
            base_filename = f"{user.id}_{timestamp}_{prefix}"
            
            kyc_dir = os.path.join('static', 'uploads', 'kyc')
            os.makedirs(kyc_dir, exist_ok=True)
            
            if ext in ['png', 'jpg', 'jpeg']:
                target_filename = f"{base_filename}.jpg"
                target_path = os.path.join(kyc_dir, target_filename)
                
                img = Image.open(file_storage)
                
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                max_width = 1200
                if img.width > max_width:
                    ratio = max_width / float(img.width)
                    height = int(float(img.height) * ratio)
                    img = img.resize((max_width, height), Image.Resampling.LANCZOS)
                
                img.save(target_path, "JPEG", quality=65, optimize=True)
                return f"uploads/kyc/{target_filename}"
            
            elif ext == 'pdf':
                target_filename = f"{base_filename}.pdf"
                target_path = os.path.join(kyc_dir, target_filename)
                file_storage.save(target_path)
                return f"uploads/kyc/{target_filename}"
            
            return None

        try:
            front_rel_path = process_kyc_image(front_file, 'front')
            back_rel_path = process_kyc_image(back_file, 'back')
            
            if not front_rel_path or not back_rel_path:
                flash('Error processing files. Please try again.', 'error')
                return redirect(url_for('user.kyc_verification'))

            user.id_front_url = front_rel_path
            user.id_back_url = back_rel_path
            user.document_type = document_type
            user.document_number = document_number
            user.kyc_status = 'submitted'
            user.kyc_submitted_at = datetime.now(timezone.utc)
            db.session.commit()
            
            flash('KYC documents submitted successfully! We will review them within 24-48 hours.', 'success')
            return redirect(url_for('user.dashboard'))
            
        except Exception as e:
            db.session.rollback()
            print(f"KYC submission error: {e}")
            flash('Error submitting KYC. Please try again.', 'error')
    
    return render_template('user/kyc_verify.html', user=user)

@user_bp.route('/kyc/status')
@login_required
def kyc_status():
    user = User.query.get(session['user_id'])
    return render_template('user/kyc_status.html', user=user)

@user_bp.route('/phone-verification')
@login_required
def phone_verification():
    user = User.query.get(session['user_id'])
    return render_template('user/phone_verification.html', user=user)


# ===== CHALLENGE ROUTES =====
@user_bp.route('/buy_challenges')
@login_required
def user_challenges():
    user = User.query.get(session['user_id'])
    user_purchases = ChallengePurchase.query.filter_by(user_id=user.id).join(ChallengeTemplate).all()
    
    # Get available challenges
    available_challenges = ChallengeTemplate.query.filter_by(is_active=True).order_by(ChallengeTemplate.price).all()
    
    return render_template('user/user_challenges.html', 
                         user=user, 
                         purchases=user_purchases,
                         challenges=available_challenges)

@user_bp.route('/challenge/<int:challenge_id>/buy')
@login_required
def buy_challenge(challenge_id):
    user = User.query.get_or_404(session['user_id'])
    challenge = ChallengeTemplate.query.get_or_404(challenge_id)

    if not challenge.is_active:
        flash('This challenge is currently unavailable.', 'error')
        return redirect(url_for('user.challenges'))

    return render_template(
        'user/buy_challenge.html',
        user=user,
        challenge=challenge
    )

# ===== TRADING ROUTES =====
@user_bp.route('/trading')
@login_required
def trading():
    user = User.query.get(session['user_id'])
    active_challenges = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(ACTIVE_CHALLENGE_STATUSES)
    ).join(ChallengeTemplate).all()
    
    now_utc = datetime.now(timezone.utc)
    for challenge in active_challenges:
        if challenge.end_date:
            end_date = challenge.end_date.replace(tzinfo=timezone.utc) if challenge.end_date.tzinfo is None else challenge.end_date
            days_left = (end_date - now_utc).days
            challenge.days_remaining = max(0, days_left)
        else:
            challenge.days_remaining = 0
    
    return render_template('user/trading.html',
                         user=user,
                         active_challenges=active_challenges)

@user_bp.route('/history')
@login_required
def user_history():
    user = User.query.get(session['user_id'])
    purchases = ChallengePurchase.query.filter(
        ChallengePurchase.user_id == user.id,
        ChallengePurchase.status.in_(HISTORY_CHALLENGE_STATUSES)
    ).order_by(ChallengePurchase.created_at.desc()).all()
    progression_requests = ProgressionRequest.query.filter_by(user_id=user.id).order_by(ProgressionRequest.created_at.desc()).all()
    
    stats = {
        'total': len(purchases),
        'passed': len([p for p in purchases if p.status == 'passed']),
        'failed': len([p for p in purchases if p.status == 'failed']),
        'active': ChallengePurchase.query.filter(
            ChallengePurchase.user_id == user.id,
            ChallengePurchase.status.in_(ACTIVE_CHALLENGE_STATUSES)
        ).count(),
        'progression_requests': len(progression_requests)
    }
    
    return render_template('user/user_history.html', user=user, purchases=purchases, progression_requests=progression_requests, stats=stats)

@user_bp.route('/trading/history')
@login_required
def trading_history():
    return redirect(url_for('user.user_history'))

@user_bp.route('/mt5-download')
@login_required
def mt5_download():
    return render_template('user/mt5_download.html')

# ===== PROFILE ROUTES =====
@user_bp.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    return render_template('user/profile.html', user=user)

@user_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    try:
        user = User.query.get(session['user_id'])
        user.first_name = request.form.get('first_name', user.first_name)
        user.last_name = request.form.get('last_name', user.last_name)
        user.phone = request.form.get('phone', user.phone)
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error updating profile. Please try again.', 'error')
    
    return redirect(url_for('user.profile'))

# ===== PAYMENT & PAYOUT ROUTES =====
@user_bp.route('/payments')
@login_required
def payments():
    user = User.query.get(session['user_id'])
    user_payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()
    
    return render_template('user/payments.html',
                         user=user,
                         payments=user_payments)

@user_bp.route('/payouts')
@login_required
def payouts():
    user = User.query.get(session['user_id'])
    purchases = ChallengePurchase.query.filter_by(user_id=user.id).order_by(ChallengePurchase.created_at.desc()).all()
    eligible_accounts = []
    blocked_accounts = []
    for purchase in purchases:
        info = payout_eligibility(purchase)
        row = {'challenge': purchase, 'info': info}
        if purchase.status in ['funded', 'funded_active'] or purchase.challenge_type == 'instant':
            eligible_accounts.append(row)
        elif purchase.status in ['active', 'passed', 'failed', 'expired', 'revoked']:
            blocked_accounts.append(row)
    user_payouts = Payout.query.filter_by(user_id=user.id).order_by(Payout.created_at.desc()).all()
    active_payouts_count = sum(1 for payout in user_payouts if payout.status in ACTIVE_PAYOUT_STATUSES)
    
    return render_template('user/payouts.html', 
                         user=user, 
                         payouts=user_payouts,
                         active_payouts_count=active_payouts_count,
                         eligible_accounts=eligible_accounts,
                         blocked_accounts=blocked_accounts)

@user_bp.route('/request-payout', methods=['POST'])
@login_required
def request_payout():
    try:
        user = User.query.get(session['user_id'])
        challenge_id = request.form.get('challenge_id', type=int)
        amount = float(request.form.get('amount', 0))
        payment_method = request.form.get('payment_method', '').strip()
        account_holder_name = request.form.get('account_holder_name', '').strip()
        
        challenge = ChallengePurchase.query.filter_by(
            id=challenge_id,
            user_id=user.id
        ).first()
        
        if not challenge:
            flash('Invalid challenge selected.', 'error')
            return redirect(url_for('user.payouts'))

        info = payout_eligibility(challenge)
        if not info['eligible']:
            flash(info['reason'] or 'This account is not eligible for payout yet.', 'error')
            return redirect(url_for('user.payouts'))
        
        if amount < info['minimum'] or amount > info['available_profit']:
            flash('Invalid payout amount.', 'error')
            return redirect(url_for('user.payouts'))

        if payment_method not in ['upi', 'bank_transfer']:
            flash('Please select a valid payout method.', 'error')
            return redirect(url_for('user.payouts'))

        if not account_holder_name:
            flash('Account holder name is required.', 'error')
            return redirect(url_for('user.payouts'))

        upi_id = ''
        bank_details = {}
        if payment_method == 'upi':
            upi_id = request.form.get('upi_id', '').strip()
            if not upi_id or '@' not in upi_id:
                flash('Please enter a valid UPI ID.', 'error')
                return redirect(url_for('user.payouts'))
        else:
            bank_details = {
                'bank_name': request.form.get('bank_name', '').strip(),
                'account_number': request.form.get('account_number', '').strip(),
                'ifsc_code': request.form.get('ifsc_code', '').strip().upper()
            }
            if not all(bank_details.values()):
                flash('Please complete all bank transfer fields.', 'error')
                return redirect(url_for('user.payouts'))
        
        payout = Payout(
            user_id=user.id,
            challenge_purchase_id=challenge.id,
            amount=amount,
            profit_share_percentage=info['profit_share'],
            status='pending',
            username_snapshot=user.get_full_name(),
            challenge_name_snapshot=challenge.challenge_template.name if challenge.challenge_template else 'Challenge',
            account_type_snapshot=info['account_type'],
            account_size_snapshot=info['account_size'],
            available_profit_snapshot=info['available_profit'],
            due_date=info['next_date'],
            payment_method=payment_method,
            account_holder_name=account_holder_name,
            upi_id=upi_id,
            bank_account_details=json.dumps(bank_details) if bank_details else ''
        )
        
        db.session.add(payout)
        db.session.flush()
        db.session.add(PayoutAuditLog(
            payout_id=payout.id,
            action='request_created',
            notes='User submitted payout request.'
        ))
        _payout_notification(user.id, 'Payout request submitted', f'Your ${amount:.2f} payout request is pending review.')
        db.session.commit()
        
        flash('Payout request submitted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error requesting payout. Please try again.', 'error')
    
    return redirect(url_for('user.payouts'))


@user_bp.route('/progression/request/<int:challenge_id>/<request_type>', methods=['POST'])
@login_required
def request_progression(challenge_id, request_type):
    try:
        user = User.query.get(session['user_id'])
        challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first_or_404()

        if request_type not in ['phase2', 'funded']:
            flash('Invalid progression request type.', 'error')
            return redirect(url_for('user.dashboard'))

        if challenge.status != 'passed':
            flash('Only passed challenges can request progression.', 'error')
            return redirect(url_for('user.dashboard'))

        if request_type == 'phase2':
            allowed = challenge.challenge_type == 'two_phase' and challenge.current_phase == 1
            submitted_title = 'Phase 2 Request Submitted'
            submitted_message = 'Your Phase 2 account request is pending admin review.'
        else:
            allowed = challenge.current_phase == 2
            submitted_title = 'Funded Request Submitted'
            submitted_message = 'Your funded account request is pending admin review.'

        if not allowed:
            flash('This challenge is not eligible for that progression request.', 'error')
            return redirect(url_for('user.dashboard'))

        existing = ProgressionRequest.query.filter(
            ProgressionRequest.challenge_purchase_id == challenge.id,
            ProgressionRequest.request_type == request_type,
            ProgressionRequest.status == 'pending'
        ).first()
        if existing:
            flash('You already have a pending progression request for this challenge.', 'info')
            return redirect(url_for('user.dashboard'))

        progression_request = ProgressionRequest(
            user_id=user.id,
            challenge_purchase_id=challenge.id,
            request_type=request_type,
            status='pending'
        )
        db.session.add(progression_request)
        _user_notification(user.id, submitted_title, submitted_message)
        db.session.commit()

        flash('Progression request submitted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Progression request error: {e}")
        flash('Error submitting progression request. Please try again.', 'error')

    return redirect(url_for('user.dashboard'))

# ===== SETTINGS ROUTES =====
@user_bp.route('/settings')
@login_required
def settings():
    user = User.query.get(session['user_id'])
    return render_template('user/settings.html', user=user)

@user_bp.route('/settings/update', methods=['POST'])
@login_required
def update_settings():
    try:
        user = User.query.get(session['user_id'])
        
        if 'trading_alias' in request.form:
            user.trading_alias = request.form.get('trading_alias', '').strip()
            
        if 'is_compact_view' in request.form:
            user.is_compact_view = request.form.get('is_compact_view') == 'true'
            
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error updating settings.', 'error')
    
    return redirect(url_for('user.settings'))

@user_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    try:
        user = User.query.get(session['user_id'])
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not user.check_password(current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('user.settings'))
        
        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('user.settings'))
        
        if len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return redirect(url_for('user.settings'))
        
        user.set_password(new_password)
        db.session.commit()
        
        flash('Password changed successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error changing password. Please try again.', 'error')
    
    return redirect(url_for('user.settings'))

@user_bp.route('/security')
@login_required
def security():
    user = User.query.get(session['user_id'])
    return render_template('user/security.html', user=user)

# ===== API ENDPOINTS FOR DASHBOARD =====
@user_bp.route('/api/challenge-progress/<int:challenge_id>')
@login_required
def api_challenge_progress(challenge_id):
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=session['user_id']
    ).first_or_404()
    
    progress_data = {
        'profit_target_percentage': challenge.progress_percentage or 0,
        'max_drawdown_used': challenge.max_drawdown_used or 0,
        'days_remaining': challenge.days_remaining or 0,
        'current_balance': challenge.current_balance or 0,
        'current_profit': challenge.current_profit or 0,
        'status': challenge.status or 'unknown'
    }
    
    return jsonify({'success': True, 'data': progress_data})

# ===== CHALLENGE ROUTES =====
@user_bp.route('/challenges')
@login_required
def challenges():
    user = User.query.get(session['user_id'])
    available_challenges = ChallengeTemplate.query.filter_by(is_active=True).all()
    user_purchases = ChallengePurchase.query.filter_by(user_id=user.id).all()
    
    return render_template('user/user_challenges.html',
                         user=user, 
                         challenges=available_challenges,
                         purchases=user_purchases)

@user_bp.route('/api/challenge/<int:challenge_id>/credentials')
@login_required
def get_challenge_credentials(challenge_id):
    user = User.query.get_or_404(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=user.id
    ).first_or_404()
    
    return jsonify({
        'success': False,
        'message': 'MT5 credentials are sent by email only and are not shown on the dashboard.'
    }), 403

@user_bp.route('/credentials/<int:challenge_id>')
@login_required
def view_credentials(challenge_id):
    user = User.query.get(session['user_id'])
    
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=user.id
    ).first_or_404()
    
    flash('MT5 credentials are sent by email only and are not shown on the dashboard.', 'info')
    return redirect(url_for('user.trading'))

@user_bp.route('/start-phase2/<int:challenge_id>', methods=['POST'])
@login_required
def start_phase2(challenge_id):
    return jsonify({
        'success': False,
        'error': 'Phase 2 accounts must be requested and approved by admin.'
    }), 403
    try:
        user = User.query.get(session['user_id'])
        
        challenge = ChallengePurchase.query.filter_by(
            id=challenge_id,
            user_id=user.id
        ).first_or_404()
        
        if challenge.phase == 2:
            return jsonify({'success': False, 'error': 'Already in Phase 2'})
        
        challenge.phase = 2
        challenge.status = 'phase2_active'
        challenge.start_date = datetime.now(timezone.utc)
        challenge.end_date = datetime.now(timezone.utc) + timedelta(days=30)
        challenge.days_remaining = 30
        challenge.current_profit = 0.0
        challenge.current_loss = 0.0
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Phase 2 started successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@user_bp.route('/trading/dashboard/<int:challenge_id>')
@login_required
def trading_dashboard(challenge_id):
    user = User.query.get(session['user_id'])
    
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=user.id
    ).first_or_404()
    
    return render_template('user/user_dashboard.html',
                         user=user,
                         challenge=challenge)

# ===== HELP CENTER & SUPPORT ROUTES =====
@user_bp.route('/help')
@login_required
def help():
    user = User.query.get(session['user_id'])
    search_query = request.args.get('search', '').strip()
    
    if search_query:
        faqs = FAQ.query.filter(
            (FAQ.question.ilike(f'%{search_query}%')) |
            (FAQ.answer.ilike(f'%{search_query}%'))
        ).order_by(FAQ.is_pinned.desc(), FAQ.created_at.desc()).all()
    else:
        faqs = FAQ.query.order_by(FAQ.is_pinned.desc(), FAQ.created_at.desc()).all()
    
    categories = {}
    for faq in faqs:
        if faq.category not in categories:
            categories[faq.category] = []
        categories[faq.category].append(faq)
    
    tickets = SupportTicket.query.filter_by(user_id=user.id).order_by(SupportTicket.updated_at.desc()).all()
    
    return render_template('user/help.html', 
                         user=user, 
                         categories=categories, 
                         tickets=tickets,
                         search_query=search_query)

@user_bp.route('/help/vote', methods=['POST'])
@login_required
def help_vote():
    data = request.get_json()
    faq_id = data.get('faq_id')
    vote = data.get('vote')
    
    faq = FAQ.query.get_or_404(faq_id)
    if vote == 'yes':
        faq.helpful_yes += 1
    elif vote == 'no':
        faq.helpful_no += 1
    
    db.session.commit()
    return jsonify({'success': True})

@user_bp.route('/support/create', methods=['GET', 'POST'])
@login_required
def ticket_create():
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        subject = request.form.get('subject')
        category = request.form.get('category')
        message_text = request.form.get('message')
        attachment = request.files.get('attachment')
        
        if not subject or not category or not message_text:
            flash('All fields are required.', 'error')
            return redirect(url_for('user.ticket_create'))
        
        ticket_number = f"TICK-{int(time.time())}-{random.randint(1000, 9999)}"
        
        ticket = SupportTicket(
            user_id=user.id,
            subject=subject,
            category=category,
            ticket_number=ticket_number,
            status='open'
        )
        
        db.session.add(ticket)
        db.session.flush()
        
        attachment_url = None
        if attachment and attachment.filename != '':
            attachment_url = compress_and_save_ticket_attachment(attachment, ticket_number)
        
        message = TicketMessage(
            ticket_id=ticket.id,
            sender_id=user.id,
            message=message_text,
            is_admin_reply=False,
            attachment_url=attachment_url
        )
        
        db.session.add(message)
        db.session.commit()
        
        flash('Support ticket created successfully!', 'success')
        return redirect(url_for('user.help'))
    
    return render_template('user/ticket_create.html', user=user)

@user_bp.route('/support/ticket/<string:ticket_number>')
@login_required
def ticket_chat(ticket_number):
    user = User.query.get(session['user_id'])
    ticket = SupportTicket.query.filter_by(ticket_number=ticket_number, user_id=user.id).first_or_404()
    
    ticket.last_user_read_at = datetime.now(timezone.utc)
    db.session.commit()
    
    messages = ticket.messages.order_by(TicketMessage.created_at.asc()).all()
    
    return render_template('user/ticket_chat.html', user=user, ticket=ticket, messages=messages)

@user_bp.route('/support/ticket/<string:ticket_number>/reply', methods=['POST'])
@login_required
def ticket_reply(ticket_number):
    user = User.query.get(session['user_id'])
    ticket = SupportTicket.query.filter_by(ticket_number=ticket_number, user_id=user.id).first_or_404()
    
    message_text = request.form.get('message')
    attachment = request.files.get('attachment')
    
    if not message_text and not attachment:
        flash('Message cannot be empty.', 'error')
        return redirect(url_for('user.ticket_chat', ticket_number=ticket_number))
    
    attachment_url = None
    if attachment and attachment.filename != '':
        attachment_url = compress_and_save_ticket_attachment(attachment, ticket_number, prefix="reply_")
    
    message = TicketMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        message=message_text or "Sent an attachment",
        is_admin_reply=False,
        attachment_url=attachment_url
    )
    
    if ticket.status == 'resolved':
        ticket.status = 'open'
    
    ticket.updated_at = datetime.now(timezone.utc)
    
    db.session.add(message)
    db.session.commit()
    
    return redirect(url_for('user.ticket_chat', ticket_number=ticket_number))

@user_bp.route('/user_analytics')
@login_required
def user_analytics():
    return render_template('user/user_analytics.html', user=User.query.get(session['user_id']))

# ===== CHALLENGE API ROUTES =====
@user_bp.route('/api/challenge/<int:challenge_id>/clear-flag', methods=['POST'])
@login_required
def api_user_clear_flag(challenge_id):
    user = User.query.get(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first()
    
    if not challenge:
        return jsonify({'success': False, 'error': 'Challenge not found'}), 404
    
    if not challenge.review_required and challenge.monitoring_status == 'active':
        challenge.status = 'active'
        challenge.monitoring_status = 'active'
        challenge.violation_reason = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Flag cleared'})
    
    return jsonify({'success': False, 'error': 'Flag cannot be cleared yet'}), 400

@user_bp.route('/history/details/<int:challenge_id>')
@login_required
def history_details(challenge_id):
    user = User.query.get(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first_or_404()
    
    violations = RuleLog.query.filter_by(challenge_id=challenge_id).order_by(RuleLog.created_at.desc()).all()
    trades = TradeHistory.query.filter_by(challenge_id=challenge_id).order_by(TradeHistory.close_time.desc()).limit(50).all()
    
    return render_template('user/history_details.html',
                         user=user,
                         challenge=challenge,
                         violations=violations,
                         trades=trades)

@user_bp.route('/api/challenge/<int:challenge_id>/history')
@login_required
def api_challenge_history(challenge_id):
    user = User.query.get(session['user_id'])
    challenge = ChallengePurchase.query.filter_by(id=challenge_id, user_id=user.id).first()
    
    if not challenge:
        return jsonify({'error': 'Challenge not found'}), 404
    
    violations = RuleLog.query.filter_by(challenge_id=challenge_id).order_by(RuleLog.created_at.desc()).all()
    trades = TradeHistory.query.filter_by(challenge_id=challenge_id).order_by(TradeHistory.close_time.desc()).limit(200).all()
    
    return jsonify({
        'success': True,
        'challenge': {
            'id': challenge.id,
            'challenge_name': challenge.challenge_template.name if challenge.challenge_template else 'Challenge',
            'status': challenge.status,
            'profit_percent': challenge.profit_percent,
            'daily_drawdown': challenge.daily_drawdown,
            'overall_drawdown': challenge.overall_drawdown,
            'trading_days': challenge.trading_days,
            'start_date': challenge.start_date.isoformat() if challenge.start_date else None,
            'end_date': challenge.end_date.isoformat() if challenge.end_date else None,
            'completed_at': challenge.completed_at.isoformat() if challenge.completed_at else None,
            'violation_reason': challenge.violation_reason,
            'pass_reason': challenge.pass_reason,
        },
        'violations': [{
            'rule_name': v.rule_name,
            'severity': v.severity,
            'message': v.message,
            'current_value': v.current_value,
            'threshold_value': v.threshold_value,
            'created_at': v.created_at.isoformat() if v.created_at else None
        } for v in violations],
        'trades': [{
            'ticket': t.ticket,
            'symbol': t.symbol,
            'lots': t.lots,
            'profit': t.profit,
            'open_time': t.open_time.isoformat() if t.open_time else None,
            'close_time': t.close_time.isoformat() if t.close_time else None
        } for t in trades]
    })

# ===== MT5 GUIDE ROUTES =====
@user_bp.route('/guide')
def guide_hub():
    return render_template('user/guide.html')

@user_bp.route('/guide/mt5-mobile')
def guide_mt5_mobile():
    return render_template('user/mt5_mobile.html')

@user_bp.route('/guide/mt5_pc')
def guide_mt5_pc():
    return render_template('user/mt5_pc.html')

# ===== FILE TOO LARGE PAGE =====
@user_bp.route('/file-too-large')
@login_required
def file_too_large():
    return render_template('user/file_too_large.html')

# ===== USER NOTIFICATION API ROUTES =====
@user_bp.route('/api/notifications', methods=['GET'])
@login_required
def api_get_notifications():
    try:
        user_id = session.get('user_id')
        now_utc = datetime.now(timezone.utc)

        notifications = Notification.query.filter(
            Notification.is_deleted == False,
            (Notification.expires_at == None) | (Notification.expires_at > now_utc),
            (Notification.is_global == True) | (Notification.target_user_id == user_id)
        ).order_by(Notification.created_at.desc()).all()

        read_mappings = {
            un.notification_id: un.is_read
            for un in UserNotification.query.filter_by(user_id=user_id).all()
        }

        results = []
        for n in notifications:
            is_read = read_mappings.get(n.id, False)
            results.append({
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'created_at': n.created_at.strftime('%Y-%m-%d %H:%M:%S') if n.created_at else '',
                'is_read': is_read,
                'is_global': n.is_global
            })

        unread_count = sum(1 for item in results if not item['is_read'])

        return jsonify({
            'success': True,
            'notifications': results,
            'unread_count': unread_count
        })

    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve notifications'})


@user_bp.route('/api/notifications/read', methods=['POST'])
@login_required
def api_mark_notifications_read():
    try:
        data = request.get_json() or {}
        notif_ids = data.get('notification_ids', [])
        notif_id = data.get('notification_id')
        
        if notif_id:
            notif_ids.append(notif_id)

        if not notif_ids:
            return jsonify({'success': False, 'error': 'No notification IDs provided'})

        user_id = session.get('user_id')
        now_utc = datetime.now(timezone.utc)

        for nid in notif_ids:
            mapping = UserNotification.query.filter_by(notification_id=nid, user_id=user_id).first()
            if mapping:
                mapping.is_read = True
                mapping.read_at = now_utc
            else:
                notif = Notification.query.filter_by(id=nid, is_deleted=False).first()
                if notif and (notif.is_global or notif.target_user_id == user_id):
                    user_notif = UserNotification(
                        notification_id=nid,
                        user_id=user_id,
                        is_read=True,
                        read_at=now_utc
                    )
                    db.session.add(user_notif)

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Error marking notifications read: {e}")
        return jsonify({'success': False, 'error': 'Failed to mark notifications as read'})


@user_bp.route('/api/notifications/read-all', methods=['POST'])
@login_required
def api_mark_all_notifications_read():
    try:
        user_id = session.get('user_id')
        now_utc = datetime.now(timezone.utc)

        notifications = Notification.query.filter(
            Notification.is_deleted == False,
            (Notification.expires_at == None) | (Notification.expires_at > now_utc),
            (Notification.is_global == True) | (Notification.target_user_id == user_id)
        ).all()

        for n in notifications:
            mapping = UserNotification.query.filter_by(notification_id=n.id, user_id=user_id).first()
            if mapping:
                if not mapping.is_read:
                    mapping.is_read = True
                    mapping.read_at = now_utc
            else:
                user_notif = UserNotification(
                    notification_id=n.id,
                    user_id=user_id,
                    is_read=True,
                    read_at=now_utc
                )
                db.session.add(user_notif)

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Error marking all notifications read: {e}")
        return jsonify({'success': False, 'error': 'Failed to mark all notifications as read'})


@user_bp.route('/my-coupons')
@login_required
def user_coupons():
    user = User.query.get(session['user_id'])
    now = datetime.now(timezone.utc)
    
    all_coupons = Coupon.query.filter_by(is_active=True, is_deleted=False).all()
    
    available_coupons = []
    for coupon in all_coupons:
        if coupon.expires_at:
            expires_at = coupon.expires_at.replace(tzinfo=timezone.utc) if coupon.expires_at.tzinfo is None else coupon.expires_at
            if expires_at < now:
                continue

        used = CouponUsage.query.filter_by(coupon_id=coupon.id, user_id=user.id).first()
        if used:
            continue
            
        if coupon.coupon_type in ['universal', 'influencer']:
            if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
                continue
            available_coupons.append(coupon)
            
        elif coupon.coupon_type == 'specific':
            assignment = CouponAssignment.query.filter_by(
                coupon_id=coupon.id, 
                user_id=user.id, 
                is_used=False
            ).first()
            if assignment:
                available_coupons.append(coupon)
                
    return render_template('user/user_coupon.html', user=user, coupons=available_coupons)


@user_bp.route('/validate-coupon', methods=['POST'])
@login_required
def validate_coupon_api():
    try:
        user_id = session.get('user_id')
        coupon_code = request.form.get('coupon_code')
        challenge_id = request.form.get('challenge_id')
        
        if not coupon_code:
            return jsonify({'success': False, 'error': 'Coupon code is required'})
            
        if not challenge_id:
            return jsonify({'success': False, 'error': 'Challenge ID is required'})
            
        challenge = ChallengeTemplate.query.get(challenge_id)
        if not challenge:
            return jsonify({'success': False, 'error': 'Challenge not found'})
            
        coupon = Coupon.query.filter_by(code=coupon_code.upper().strip(), is_deleted=False).first()
        if not coupon:
            return jsonify({'success': False, 'error': 'Invalid coupon code'})
            
        is_valid, msg, discount_amount, final_price = coupon.validate_for_user_and_price(user_id, float(challenge.price))
        
        if not is_valid:
            return jsonify({'success': False, 'error': msg})
            
        return jsonify({
            'success': True,
            'message': msg,
            'discount_amount': discount_amount,
            'final_price': final_price,
            'coupon_type': coupon.coupon_type,
            'discount_type': coupon.discount_type,
            'discount_value': coupon.discount_value
        })
        
    except Exception as e:
        print(f"Error validating coupon: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while validating the coupon'})

# ===== TRADING CALENDAR API =====
@user_bp.route('/api/calendar')
@login_required
def api_trading_calendar():
    try:
        user_id = session.get('user_id')
        month_str = request.args.get('month')  # format: 2026-06
        
        if month_str:
            try:
                year, month = int(month_str.split('-')[0]), int(month_str.split('-')[1])
            except:
                year, month = datetime.now(timezone.utc).year, datetime.now(timezone.utc).month
        else:
            year, month = datetime.now(timezone.utc).year, datetime.now(timezone.utc).month

        # Get all challenges for this user (all time, not just active)
        all_challenges = ChallengePurchase.query.filter_by(user_id=user_id).all()
        challenge_map = {c.id: c for c in all_challenges}

        if not all_challenges:
            return jsonify({'success': True, 'days': {}, 'summary': {}})

        challenge_ids = [c.id for c in all_challenges]

        # Date range for the month
        from calendar import monthrange
        _, days_in_month = monthrange(year, month)
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        month_end = datetime(year, month, days_in_month, 23, 59, 59, tzinfo=timezone.utc)

        # Fetch all closed trades for this month across all challenges
        trades = TradeHistory.query.filter(
            TradeHistory.challenge_id.in_(challenge_ids),
            TradeHistory.is_open == False,
            TradeHistory.close_time >= month_start,
            TradeHistory.close_time <= month_end
        ).order_by(TradeHistory.close_time.asc()).all()

        # Group by date
        days = {}
        for t in trades:
            if not t.close_time:
                continue
            close_utc = t.close_time.replace(tzinfo=timezone.utc) if t.close_time.tzinfo is None else t.close_time
            day_key = close_utc.strftime('%Y-%m-%d')
            
            if day_key not in days:
                days[day_key] = {
                    'date': day_key,
                    'total_profit': 0.0,
                    'total_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'trades': []
                }
            
            profit = float(t.profit or 0)
            challenge = challenge_map.get(t.challenge_id)
            challenge_name = challenge.challenge_template.name if challenge and challenge.challenge_template else 'Challenge'
            
            days[day_key]['total_profit'] = round(days[day_key]['total_profit'] + profit, 2)
            days[day_key]['total_trades'] += 1
            if profit > 0:
                days[day_key]['winning_trades'] += 1
            elif profit < 0:
                days[day_key]['losing_trades'] += 1
            
            days[day_key]['trades'].append({
                'ticket': t.ticket,
                'symbol': t.symbol,
                'lots': t.lots,
                'profit': round(profit, 2),
                'open_time': t.open_time.isoformat() if t.open_time else None,
                'close_time': t.close_time.isoformat() if t.close_time else None,
                'challenge_name': challenge_name,
                'challenge_id': t.challenge_id
            })

        # Monthly summary
        all_trades_flat = [t for day in days.values() for t in day['trades']]
        total_profit = round(sum(t['profit'] for t in all_trades_flat), 2)
        total_trades = len(all_trades_flat)
        winning = sum(1 for t in all_trades_flat if t['profit'] > 0)
        win_rate = round(winning / total_trades * 100, 1) if total_trades > 0 else 0
        best_trade = max(all_trades_flat, key=lambda t: t['profit']) if all_trades_flat else None
        
        # Win streak
        sorted_trades = sorted(all_trades_flat, key=lambda t: t['close_time'] or '')
        streak = 0
        for t in reversed(sorted_trades):
            if t['profit'] > 0:
                streak += 1
            else:
                break

        # Most traded symbol
        from collections import Counter
        symbol_counts = Counter(t['symbol'] for t in all_trades_flat)
        top_symbol = symbol_counts.most_common(1)[0][0] if symbol_counts else None

        summary = {
            'total_profit': total_profit,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'win_streak': streak,
            'best_trade': best_trade,
            'top_symbol': top_symbol,
            'month': month_str or f'{year}-{month:02d}'
        }

        return jsonify({
            'success': True,
            'days': days,
            'summary': summary
        })

    except Exception as e:
        print(f"Calendar API error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
