from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
from models import db, User, ChallengeTemplate, ChallengePurchase, Payment, Payout
from datetime import datetime, timezone, timedelta
import os
import secrets
import random
from werkzeug.utils import secure_filename

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
        if not user.email_verified or not user.phone_verified:
            flash('Please verify your email and phone number first.', 'error')
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
        
        try:
            # Create user upload directory
            user_upload_dir = os.path.join('static/uploads', str(user.id))
            os.makedirs(user_upload_dir, exist_ok=True)
            
            # Save front file
            front_filename = f"front_{secrets.token_hex(8)}_{secure_filename(front_file.filename)}"
            front_path = os.path.join(user_upload_dir, front_filename)
            front_file.save(front_path)
            
            # Save back file
            back_filename = f"back_{secrets.token_hex(8)}_{secure_filename(back_file.filename)}"
            back_path = os.path.join(user_upload_dir, back_filename)
            back_file.save(back_path)
            
            # Update user KYC status
            user.document_type = document_type
            user.document_number = document_number
            user.kyc_status = 'submitted'
            user.kyc_submitted_at = datetime.now(timezone.utc)
            user.id_front_url = f"/static/uploads/{user.id}/{front_filename}"
            user.id_back_url = f"/static/uploads/{user.id}/{back_filename}"
            
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

# ===== PHONE VERIFICATION ROUTES =====
@user_bp.route('/send-phone-verification')
@login_required
def send_phone_verification():
    user = User.query.get(session['user_id'])
    
    # Generate OTP
    otp_code = str(random.randint(100000, 999999))
    
    # Save OTP to user
    user.phone_verification_code = otp_code
    
    # ✅ FIX: Add .timestamp() or use time.time()
    import time
    user.phone_verification_sent_at = datetime.now(timezone.utc).timestamp()  # ← ADD .timestamp()
    # OR simpler: user.phone_verification_sent_at = time.time()
    
    user.phone_verification_attempts = 0
    db.session.commit()
    
    # In production, send SMS here
    # For testing, we'll just show it
    print(f"📱 OTP for {user.phone}: {otp_code}")
    print(f"⏰ Sent at timestamp: {user.phone_verification_sent_at}")
    
    flash(f'OTP sent to your phone! Test OTP: {otp_code}', 'success')
    return redirect(url_for('user.verify_phone_otp'))

@user_bp.route('/verify-phone-otp', methods=['GET', 'POST'])
@login_required
def verify_phone_otp():
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        entered_otp = request.form.get('otp_code', '').strip()
        
        if not user.phone_verification_code:
            flash('Please request a new OTP code.', 'error')
            return redirect(url_for('user.send_phone_verification'))
        
        # ✅ FIX: Convert timestamp back to datetime for comparison
        import time
        from datetime import datetime, timezone, timedelta
        
        if user.phone_verification_sent_at:
            # Convert float timestamp to datetime
            sent_time = datetime.fromtimestamp(user.phone_verification_sent_at, tz=timezone.utc)
            time_elapsed = datetime.now(timezone.utc) - sent_time
            
            if time_elapsed.total_seconds() > 600:
                flash('OTP has expired. Please request a new one.', 'error')
                return redirect(url_for('user.send_phone_verification'))
        
        if user.phone_verification_attempts >= 3:
            flash('Too many failed attempts. Please request a new OTP.', 'error')
            return redirect(url_for('user.send_phone_verification'))
        
        if entered_otp == user.phone_verification_code:
            user.phone_verified = True
            user.phone_verification_code = None
            user.phone_verification_sent_at = None  # Clear timestamp too
            user.phone_verification_attempts = 0
            db.session.commit()
            
            flash('Phone number verified successfully!', 'success')
            return redirect(url_for('user.kyc'))
        else:
            user.phone_verification_attempts += 1
            db.session.commit()
            
            attempts_left = 3 - user.phone_verification_attempts
            flash(f'Invalid OTP code. {attempts_left} attempts remaining.', 'error')
    
    return render_template('user/verify_phone_otp.html', user=user)

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

@user_bp.route('/purchase_challenge', methods=['POST'])
@login_required
def purchase_challenge():
    try:
        # ✅ FIX: Lock user row to prevent race conditions in purchase limit
        # This serializes purchase requests for the same user
        user = User.query.with_for_update().filter_by(id=session['user_id']).first_or_404()

        challenge_id = request.form.get('challenge_id')
        payment_method = request.form.get('payment_method')

        if not challenge_id or not payment_method:
            flash('Missing required information', 'error')
            return redirect(url_for('user.challenges'))

        challenge = ChallengeTemplate.query.get_or_404(challenge_id)

        # Challenge must be active
        if not challenge.is_active:
            flash('This challenge is currently unavailable', 'error')
            return redirect(url_for('user.challenges'))

        # KYC check
        if user.kyc_status != 'approved':
            flash('Please complete KYC verification before purchasing', 'error')
            return redirect(url_for('user.kyc'))

        # 🔒 PER-DAY LIMIT (MAX 3 PURCHASES PER DAY)
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)

        # Start of today (00:00 UTC)
        start_of_today = datetime(
            year=now.year,
            month=now.month,
            day=now.day,
            tzinfo=timezone.utc
        )

        today_count = ChallengePurchase.query.filter(
            ChallengePurchase.user_id == user.id,
            ChallengePurchase.challenge_template_id == challenge.id,
            ChallengePurchase.purchase_date >= start_of_today
        ).count()

        if today_count >= 3:
            flash(
                'Daily purchase limit reached (max 3 per day for this challenge). '
                'Please try again tomorrow.',
                'error'
            )
            return redirect(url_for('user.challenges'))

        # ✅ CREATE NEW PURCHASE (ALWAYS ALLOWED IF < 3 TODAY)
        purchase = ChallengePurchase(
            user_id=user.id,
            challenge_template_id=challenge.id,
            purchase_date=now,
            amount=challenge.price,
            payment_method=payment_method,
            status='pending_credentials',  # ✅ FIXED: Changed from 'pending_payment'
            start_date=now,
            end_date=now + timedelta(days=challenge.duration_days),
            mt5_account=f"TRG_{user.id}_{challenge.id}_{int(now.timestamp())}"
        )

        db.session.add(purchase)
        db.session.commit()

        flash('Challenge purchase initiated successfully', 'success')
        return redirect(url_for('user.dashboard'))

    except Exception as e:
        db.session.rollback()
        print(f"Purchase error: {e}")
        flash('Error processing your purchase. Please try again.', 'error')
        return redirect(url_for('user.challenges'))

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
    available_challenges = ChallengeTemplate.query.filter_by(is_active=True, phase=1).all()
    
    # ===== DEEP DEBUG =====
    print("\n🔍 DEEP CHALLENGE DATA DEBUG:")
    for i, c in enumerate(available_challenges, 1):
        print(f"\nChallenge {i}:")
        print(f"  ID: {c.id}")
        print(f"  Name: {c.name}")
        print(f"  Price: ₹{c.price}")
        print(f"  Account Size: {c.account_size} (type: {type(c.account_size)})")
        print(f"  Profit Target: {c.profit_target}%")
        print(f"  Max Daily Loss: {c.max_daily_loss}%")
        print(f"  Max Overall Loss: {c.max_overall_loss}%")
        print(f"  Min Days: {c.min_trading_days}")
        print(f"  Duration: {c.duration_days} days")
        print(f"  Profit Share: {c.user_profit_share}%")
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




