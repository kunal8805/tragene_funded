from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
from models import db, User, ChallengeTemplate, ChallengePurchase, Payment, Payout, SupportTicket, TicketMessage, FAQ
from datetime import datetime, timezone, timedelta
import os
import secrets
import random
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
    
    # Get user's active challenges
    active_challenges = ChallengePurchase.query.filter_by(
        user_id=user.id, 
        status='active'
    ).join(ChallengeTemplate).all()
    
    # Calculate days remaining dynamically for each challenge
    now_utc = datetime.now(timezone.utc)
    for challenge in active_challenges:
        if challenge.end_date:
            # Ensure end_date is timezone-aware
            end_date = challenge.end_date.replace(tzinfo=timezone.utc) if challenge.end_date.tzinfo is None else challenge.end_date
            days_left = (end_date - now_utc).days
            challenge.days_remaining = max(0, days_left)  # Don't show negative days
        else:
            challenge.days_remaining = 0
    
    # Get recent activity (last 7 days)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_payouts = Payout.query.filter(
        Payout.user_id == user.id,
        Payout.created_at >= seven_days_ago
    ).order_by(Payout.created_at.desc()).limit(5).all()
    
    return render_template('user/user_dashboard.html',
                         user=user, 
                         active_challenges=active_challenges,
                         recent_payouts=recent_payouts)

@user_bp.route('/dashboard/stats')
@login_required
def dashboard_stats():
    """API endpoint for dashboard statistics"""
    user = User.query.get(session['user_id'])
    
    # Mock data - replace with actual calculations
    stats = {
        'account_balance': 10000,
        'current_profit': 0,
        'drawdown_used': 0,
        'days_remaining': 30,
        'profit_target_percentage': 0,
        'max_drawdown_percentage': 0,
        'time_remaining_percentage': 100
    }
    
    return jsonify(stats)

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
        
        # Check file extensions
        def allowed_file(filename):
            return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'pdf'}
        
        if not (allowed_file(front_file.filename) and allowed_file(back_file.filename)):
            flash('Only PNG, JPG, JPEG, and PDF files are allowed.', 'error')
            return redirect(url_for('user.kyc_verification'))
        
        # Helper to process and compress images
        def process_kyc_image(file_storage, prefix):
            """
            Process KYC file:
            1. If Image: Resize (max 1200px width), Compress (65% quality), Convert to JPEG.
            2. If PDF: Save as is.
            Returns: Relative path to saved file.
            """
            ext = file_storage.filename.rsplit('.', 1)[1].lower()
            timestamp = int(time.time())
            
            # Create unique filename
            # userid_timestamp_front.jpg
            base_filename = f"{user.id}_{timestamp}_{prefix}"
            
            # Ensure upload directory exists
            kyc_dir = os.path.join('static', 'uploads', 'kyc')
            os.makedirs(kyc_dir, exist_ok=True)
            
            if ext in ['png', 'jpg', 'jpeg']:
                target_filename = f"{base_filename}.jpg"
                target_path = os.path.join(kyc_dir, target_filename)
                
                # Open image using Pillow
                img = Image.open(file_storage)
                
                # Convert to RGB (required for saving as JPEG if source is RGBA)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                # Resize if wider than 1200px
                max_width = 1200
                if img.width > max_width:
                    ratio = max_width / float(img.width)
                    height = int(float(img.height) * ratio)
                    img = img.resize((max_width, height), Image.Resampling.LANCZOS)
                
                # Save compressed JPEG
                img.save(target_path, "JPEG", quality=65, optimize=True)
                return f"uploads/kyc/{target_filename}"
            
            elif ext == 'pdf':
                target_filename = f"{base_filename}.pdf"
                target_path = os.path.join(kyc_dir, target_filename)
                file_storage.save(target_path)
                return f"uploads/kyc/{target_filename}"
            
            return None

        try:
            # Process files
            front_rel_path = process_kyc_image(front_file, 'front')
            back_rel_path = process_kyc_image(back_file, 'back')
            
            if not front_rel_path or not back_rel_path:
                flash('Error processing files. Please try again.', 'error')
                return redirect(url_for('user.kyc_verification'))

            # Update user KYC status
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


# ===== CHALLENGE ROUTES =====
@user_bp.route('/buy_challenges')  # ✅ FIXED: Added leading slash
@login_required
def user_challenges():
    user = User.query.get(session['user_id'])
    user_purchases = ChallengePurchase.query.filter_by(user_id=user.id).join(ChallengeTemplate).all()
    
    return render_template('user/user_challenges.html', 
                         user=user, 
                         purchases=user_purchases)

@user_bp.route('/challenge/<int:challenge_id>/buy')
@login_required
def buy_challenge(challenge_id):
    user = User.query.get_or_404(session['user_id'])
    challenge = ChallengeTemplate.query.get_or_404(challenge_id)

    # Only check if challenge is active
    if not challenge.is_active:
        flash('This challenge is currently unavailable.', 'error')
        return redirect(url_for('user.challenges'))

    # ✅ NO anti-spam here
    # ✅ NO already_purchased
    # ✅ NO ownership checks
    # GET route must ONLY show page

    return render_template(
        'user/buy_challenge.html',
        user=user,
        challenge=challenge
    )

# Route removed: Challenges are now provisioned via Cashfree Webhooks only.

# ===== TRADING ROUTES =====
@user_bp.route('/trading')
@login_required
def trading():
    user = User.query.get(session['user_id'])
    active_challenges = ChallengePurchase.query.filter_by(
        user_id=user.id, 
        status='active'
    ).join(ChallengeTemplate).all()
    
    # Calculate days remaining dynamically for each challenge
    now_utc = datetime.now(timezone.utc)
    for challenge in active_challenges:
        if challenge.end_date:
            # Ensure end_date is timezone-aware
            end_date = challenge.end_date.replace(tzinfo=timezone.utc) if challenge.end_date.tzinfo is None else challenge.end_date
            days_left = (end_date - now_utc).days
            challenge.days_remaining = max(0, days_left)  # Don't show negative days
        else:
            challenge.days_remaining = 0
    
    return render_template('user/trading.html',
                         user=user,
                         active_challenges=active_challenges)

@user_bp.route('/history')
@login_required
def user_history():
    user = User.query.get(session['user_id'])
    purchases = ChallengePurchase.query.filter_by(user_id=user.id).all()
    
    stats = {
        'total': len(purchases),
        'passed': len([p for p in purchases if p.status == 'passed']),
        'failed': len([p for p in purchases if p.status == 'failed']),
        'active': len([p for p in purchases if p.status == 'active' or p.status == 'pending_credentials'])
    }
    
    return render_template('user/user_history.html', user=user, purchases=purchases, stats=stats)

@user_bp.route('/trading/history')
@login_required
def trading_history():
    return redirect(url_for('user.user_history'))

@user_bp.route('/mt5-download')
@login_required
def mt5_download():
    """Serve MT5 download links"""
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
    user_payouts = Payout.query.filter_by(user_id=user.id).join(ChallengePurchase).all()
    
    return render_template('user/payouts.html', 
                         user=user, 
                         payouts=user_payouts)

@user_bp.route('/request-payout', methods=['POST'])
@login_required
def request_payout():
    try:
        user = User.query.get(session['user_id'])
        challenge_id = request.form.get('challenge_id')
        amount = float(request.form.get('amount', 0))
        
        challenge = ChallengePurchase.query.filter_by(
            id=challenge_id,
            user_id=user.id,
            status='active'
        ).first()
        
        if not challenge:
            flash('Invalid challenge selected.', 'error')
            return redirect(url_for('user.payouts'))
        
        if amount <= 0 or amount > challenge.current_profit:
            flash('Invalid payout amount.', 'error')
            return redirect(url_for('user.payouts'))
        
        # Create payout request
        payout = Payout(
            user_id=user.id,
            challenge_purchase_id=challenge.id,
            amount=amount,
            status='pending',
            payout_method=request.form.get('payout_method', 'bank_transfer')
        )
        
        db.session.add(payout)
        db.session.commit()
        
        flash('Payout request submitted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error requesting payout. Please try again.', 'error')
    
    return redirect(url_for('user.payouts'))

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
        
        # Update Trading Alias
        if 'trading_alias' in request.form:
            user.trading_alias = request.form.get('trading_alias', '').strip()
            
        # Update Compact View
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
    """API endpoint for challenge progress data"""
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=session['user_id']
    ).first_or_404()
    
    progress_data = {
        'profit_target_percentage': challenge.progress_percentage,
        'max_drawdown_used': challenge.max_drawdown_used,
        'days_remaining': challenge.days_remaining,
        'current_balance': challenge.current_balance,
        'current_profit': challenge.current_profit,
        'status': challenge.status
    }
    
    return jsonify(progress_data)



# ===== CHALLENGE ROUTES =====
@user_bp.route('/challenges')
@login_required
def challenges():
    user = User.query.get(session['user_id'])
    available_challenges = ChallengeTemplate.query.filter_by(is_active=True).all()
    
    # ===== DEEP DEBUG =====
    print("\n🔍 DEEP CHALLENGE DATA DEBUG:")
    for i, c in enumerate(available_challenges, 1):
        print(f"\nChallenge {i}:")
        print(f"  ID: {c.id}")
        print(f"  Name: {c.name}")
        print(f"  Price: ₹{c.price}")
        print(f"  Account Size: {c.account_size} (type: {type(c.account_size)})")
        print(f"  Type: {c.challenge_type}")
        print(f"  Phase1 Target: {c.phase1_target}%")
        print(f"  Phase2 Target: {c.phase2_target}%")
        print(f"  Is Active: {c.is_active}")
    # ===== END DEBUG =====
    
    return render_template('user/user_challenges.html',
                         user=user, 
                         challenges=available_challenges,
                         user_purchases=[])



@user_bp.route('/api/challenge/<int:challenge_id>/credentials')
@login_required
def get_challenge_credentials(challenge_id):
    # ✅ FIXED: Using session['user_id'] instead of current_user
    user = User.query.get_or_404(session['user_id'])

    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=user.id
    ).first_or_404()
    
    return jsonify({
        'success': True,
        'challenge_name': challenge.challenge_template.name,
        'mt5_server': challenge.mt5_server,
        'mt5_login': challenge.mt5_login,
        'mt5_password': challenge.mt5_password
    })

# Add to user_routes.py
@user_bp.route('/credentials/<int:challenge_id>')
@login_required
def view_credentials(challenge_id):
    """Show MT5 credentials page for a specific challenge"""
    user = User.query.get(session['user_id'])
    
    # Get challenge purchase
    challenge = ChallengePurchase.query.filter_by(
        id=challenge_id,
        user_id=user.id
    ).first_or_404()
    
    # Security check: only show if challenge is active and has credentials
    if challenge.status != 'active' or not challenge.mt5_login:
        flash('Credentials not available for this challenge', 'error')
        return redirect(url_for('user.trading'))
    
    return render_template('user/credentials.html',
                         user=user,
                         challenge=challenge)

@user_bp.route('/start-phase2/<int:challenge_id>', methods=['POST'])
@login_required
def start_phase2(challenge_id):
    """Start Phase 2 of a challenge"""
    try:
        user = User.query.get(session['user_id'])
        
        # Get challenge
        challenge = ChallengePurchase.query.filter_by(
            id=challenge_id,
            user_id=user.id,
            phase=1,
            status='passed'
        ).first_or_404()
        
        # Check if already in Phase 2
        if challenge.phase == 2:
            return jsonify({'success': False, 'error': 'Already in Phase 2'})
        
        # Update to Phase 2
        challenge.phase = 2
        challenge.status = 'active'
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
    """Trading analytics dashboard for a specific challenge"""
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
    
    # Group FAQs by category
    categories = {}
    for faq in faqs:
        if faq.category not in categories:
            categories[faq.category] = []
        categories[faq.category].append(faq)
    
    # Get user's tickets
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
    vote = data.get('vote') # 'yes' or 'no'
    
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
        
        # Generate ticket number
        ticket_number = f"TICK-{int(time.time())}-{random.randint(1000, 9999)}"
        
        ticket = SupportTicket(
            user_id=user.id,
            subject=subject,
            category=category,
            ticket_number=ticket_number,
            status='open'
        )
        
        db.session.add(ticket)
        db.session.flush() # Get ticket.id
        
        # Save attachment if exists
        attachment_url = None
        if attachment and attachment.filename != '':
            attachment_url = compress_and_save_ticket_attachment(attachment, ticket_number)
        
        # Create initial message
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
    
    # Mark as read by user
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
    
    # Save attachment if exists
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
    
    # Update ticket status if it was resolved
    if ticket.status == 'resolved':
        ticket.status = 'open'
    
    ticket.updated_at = datetime.now(timezone.utc)
    
    db.session.add(message)
    db.session.commit()
    
    return redirect(url_for('user.ticket_chat', ticket_number=ticket_number))
