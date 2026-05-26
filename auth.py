from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, date, timezone, timedelta
import secrets
import random
from functools import wraps
from models import db, User
import os
import json

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False

auth_bp = Blueprint('auth', __name__)

# ===== REDIS RATE LIMITING STORAGE (PRODUCTION) =====
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
USE_REDIS = REDIS_AVAILABLE and (os.getenv('REDIS_ENABLED', 'true').lower() == 'true')

# Initialize Redis connection for production
redis_client = None
if USE_REDIS and redis is not None:
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()  # Test connection
        print("[OK] Redis connected for rate limiting")
        USE_REDIS = True
    except Exception as e:
        print(f"[WARNING] Redis connection failed: {e}. Falling back to memory storage")
        USE_REDIS = False

# Rate limit configuration
MAX_LOGIN_ATTEMPTS = 5          # Max failed login attempts per email
MAX_RESET_ATTEMPTS = 3          # Max password reset requests per email
MAX_IP_ATTEMPTS = 20            # Max total attempts per IP
LOCKOUT_MINUTES = 15            # Lockout duration in minutes
RESET_COOLDOWN_MINUTES = 5      # Cooldown between reset requests

def get_redis_key(prefix, identifier):
    """Generate Redis key with expiry"""
    return f"ratelimit:{prefix}:{identifier}"

def get_failed_attempts(email, ip, attempt_type='login'):
    """Get failed attempts from Redis or memory"""
    if USE_REDIS:
        key = get_redis_key(attempt_type, email)
        data = redis_client.get(key)
        if data:
            return json.loads(data)
        return {'count': 0, 'locked_until': None, 'timestamp': None}
    else:
        # Fallback to memory storage
        if attempt_type == 'login':
            return failed_login_attempts.get(email, {'count': 0, 'locked_until': None, 'timestamp': None})
        else:
            return failed_reset_attempts.get(email, {'count': 0, 'cooldown_until': None, 'timestamp': None})

def set_failed_attempts(email, data, attempt_type='login', expiry=3600):
    """Store failed attempts in Redis or memory"""
    if USE_REDIS:
        key = get_redis_key(attempt_type, email)
        redis_client.setex(key, expiry, json.dumps(data))
    else:
        # Fallback to memory storage
        if attempt_type == 'login':
            failed_login_attempts[email] = data
        else:
            failed_reset_attempts[email] = data

def delete_failed_attempts(email, attempt_type='login'):
    """Delete failed attempts from Redis or memory"""
    if USE_REDIS:
        key = get_redis_key(attempt_type, email)
        redis_client.delete(key)
    else:
        if attempt_type == 'login' and email in failed_login_attempts:
            del failed_login_attempts[email]
        elif attempt_type == 'reset' and email in failed_reset_attempts:
            del failed_reset_attempts[email]

def get_ip_attempts(ip):
    """Get IP attempts from Redis or memory"""
    if USE_REDIS:
        key = get_redis_key('ip', ip)
        data = redis_client.get(key)
        if data:
            return json.loads(data)
        return {'count': 0, 'locked_until': None, 'timestamp': None}
    else:
        return ip_attempts.get(ip, {'count': 0, 'locked_until': None, 'timestamp': None})

def set_ip_attempts(ip, data, expiry=3600):
    """Store IP attempts in Redis or memory"""
    if USE_REDIS:
        key = get_redis_key('ip', ip)
        redis_client.setex(key, expiry, json.dumps(data))
    else:
        ip_attempts[ip] = data

def delete_ip_attempts(ip):
    """Delete IP attempts from Redis or memory"""
    if USE_REDIS:
        key = get_redis_key('ip', ip)
        redis_client.delete(key)
    elif ip in ip_attempts:
        del ip_attempts[ip]

# Memory fallback storage (only used if Redis is not available)
failed_login_attempts = {}
failed_reset_attempts = {}
ip_attempts = {}

def get_client_ip():
    """Get client's real IP address behind proxy"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr or 'unknown'

def is_login_rate_limited(email, ip):
    """Check if login attempts are rate limited"""
    now = datetime.now(timezone.utc)
    
    # Check email lockout
    email_data = get_failed_attempts(email, ip, 'login')
    if email_data.get('locked_until'):
        locked_until = datetime.fromisoformat(email_data['locked_until']) if isinstance(email_data['locked_until'], str) else email_data['locked_until']
        if locked_until and locked_until > now:
            remaining = int((locked_until - now).total_seconds())
            return True, f"Too many failed attempts. Please try again in {remaining} seconds."
    
    # Check IP lockout
    ip_data = get_ip_attempts(ip)
    if ip_data.get('locked_until'):
        locked_until = datetime.fromisoformat(ip_data['locked_until']) if isinstance(ip_data['locked_until'], str) else ip_data['locked_until']
        if locked_until and locked_until > now:
            remaining = int((locked_until - now).total_seconds())
            return True, f"Too many attempts from your IP. Please try again in {remaining} seconds."
    
    return False, None

def is_reset_rate_limited(email, ip):
    """Check if password reset requests are rate limited"""
    now = datetime.now(timezone.utc)
    
    # Check email reset cooldown
    reset_data = get_failed_attempts(email, ip, 'reset')
    if reset_data.get('cooldown_until'):
        cooldown_until = datetime.fromisoformat(reset_data['cooldown_until']) if isinstance(reset_data['cooldown_until'], str) else reset_data['cooldown_until']
        if cooldown_until and cooldown_until > now:
            remaining = int((cooldown_until - now).total_seconds())
            return True, f"Please wait {remaining} seconds before requesting another reset email."
    
    return False, None

def record_failed_login(email, ip):
    """Record a failed login attempt"""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    
    # Get current attempts
    email_data = get_failed_attempts(email, ip, 'login')
    email_data['count'] = email_data.get('count', 0) + 1
    email_data['timestamp'] = now_iso
    
    # Lock if exceeded max attempts
    if email_data['count'] >= MAX_LOGIN_ATTEMPTS:
        locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        email_data['locked_until'] = locked_until.isoformat()
    
    # Store updated attempts
    set_failed_attempts(email, email_data, 'login', LOCKOUT_MINUTES * 60)
    
    # Record IP attempt
    ip_data = get_ip_attempts(ip)
    ip_data['count'] = ip_data.get('count', 0) + 1
    ip_data['timestamp'] = now_iso
    
    # Lock IP if exceeded max attempts
    if ip_data['count'] >= MAX_IP_ATTEMPTS:
        locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        ip_data['locked_until'] = locked_until.isoformat()
    
    # Store IP attempts
    set_ip_attempts(ip, ip_data, LOCKOUT_MINUTES * 60)

def record_reset_request(email, ip):
    """Record a password reset request"""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    
    # Get current reset attempts
    reset_data = get_failed_attempts(email, ip, 'reset')
    reset_data['count'] = reset_data.get('count', 0) + 1
    reset_data['timestamp'] = now_iso
    cooldown_until = now + timedelta(minutes=RESET_COOLDOWN_MINUTES)
    reset_data['cooldown_until'] = cooldown_until.isoformat()
    
    # Store updated attempts
    set_failed_attempts(email, reset_data, 'reset', 3600)

def reset_failed_attempts(email, ip):
    """Reset failed attempts after successful login"""
    delete_failed_attempts(email, 'login')
    # Don't delete IP attempts immediately to prevent rapid cycling

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        client_ip = get_client_ip()
        
        # Check rate limits
        is_limited, limit_message = is_login_rate_limited(email, client_ip)
        if is_limited:
            flash(limit_message, 'error')
            return render_template('login.html')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password) and not user.is_banned:
            # Successful login - reset attempts
            reset_failed_attempts(email, client_ip)
            session.clear()
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['user_name'] = f"{user.first_name} {user.last_name}"
            session['is_admin'] = user.is_admin
            session['user_role'] = getattr(user, 'role', 'user') or 'user'
            session.permanent = True
            flash(f'Welcome back, {user.first_name}!', 'success')
            
            # Redirect based on role
            if user.is_admin:
                return redirect(url_for('admin.admin_dashboard'))
            elif getattr(user, 'role', 'user') == 'partner':
                return redirect(url_for('partner.dashboard'))
            else:
                return redirect(url_for('user.dashboard'))
        elif user and user.is_banned:
            flash('Your account has been banned. Please contact support.', 'error')
        else:
            # Failed login - record attempt
            record_failed_login(email, client_ip)
            
            # Show remaining attempts
            email_data = get_failed_attempts(email, client_ip, 'login')
            remaining = max(0, MAX_LOGIN_ATTEMPTS - email_data.get('count', 0))
            
            if remaining > 0:
                flash(f'Invalid email or password. {remaining} attempt(s) remaining.', 'error')
            else:
                flash(f'Too many failed attempts. Account temporarily locked for {LOCKOUT_MINUTES} minutes.', 'error')
    
    return render_template('login.html')

@auth_bp.route('/secret-registration')
def secret_registration():
    """Hidden route to access registration page during pre-launch"""
    return render_template('register.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        phone = request.form['phone']
        dob = request.form['dob']
        country = request.form['country']
        state = request.form.get('state', '')
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        try:
            dob_date = datetime.strptime(dob, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date of birth format.', 'error')
            return render_template('register.html')
        
        age = date.today().year - dob_date.year - ((date.today().month, date.today().day) < (dob_date.month, dob_date.day))
        
        if age < 18:
            flash('You must be 18 years or older.', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('auth.login'))
        
        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            dob=dob_date,
            country=country,
            state=state if country == 'India' else None
        )
        new_user.set_password(password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            flash('Registration failed. Please try again.', 'error')
            return render_template('register.html')
    
    return render_template('register.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home'))

@auth_bp.route('/send-verification-email')
@login_required
def send_verification_email():
    user = User.query.get(session['user_id'])

    if user.email_verified:
        flash('Email already verified!', 'success')
        return redirect(url_for('user.kyc'))

    verification_token = secrets.token_urlsafe(32)
    user.email_verification_token = verification_token
    db.session.commit()

    verification_link = url_for(
        'auth.verify_email_token',
        token=verification_token,
        _external=True
    )

    html = f"""
    <div style="font-family:Arial;padding:20px;">
        <h2>Verify Your Email</h2>
        <p>Hello {user.first_name},</p>
        <p>Click the button below to verify your email address.</p>
        <a href="{verification_link}"
           style="
               background:#16a34a;
               color:white;
               padding:12px 20px;
               border-radius:8px;
               text-decoration:none;
               display:inline-block;
           ">
           Verify Email
        </a>
        <p style="margin-top:20px;">
            If you did not create this account, please ignore this email.
        </p>
    </div>
    """

    # Lazy import to avoid circular dependency
    from app import send_test_email
    send_test_email(
        user.email,
        "Verify Your Email - Tragene Funded",
        html
    )

    flash('Verification email sent successfully!', 'success')
    return redirect(url_for('user.kyc'))

@auth_bp.route('/verify-email/<token>')
def verify_email_token(token):
    user = User.query.filter_by(email_verification_token=token).first()
    if user:
        user.email_verified = True
        user.email_verification_token = None
        db.session.commit()
        if 'user_id' not in session:
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['user_name'] = f"{user.first_name} {user.last_name}"
        flash('Email verified successfully!', 'success')
    else:
        flash('Invalid verification link.', 'error')
    return redirect(url_for('user.dashboard'))

@auth_bp.route('/resend-phone-otp')
@login_required
def resend_phone_otp():
    return redirect(url_for('auth.send_phone_verification'))

@auth_bp.route('/verify/phone')
@login_required
def verify_phone():
    return redirect(url_for('auth.verify_phone_otp'))

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        client_ip = get_client_ip()
        
        # Check rate limits for password reset
        is_limited, limit_message = is_reset_rate_limited(email, client_ip)
        if is_limited:
            flash(limit_message, 'error')
            return redirect(url_for('auth.login'))
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Record the reset request
            record_reset_request(email, client_ip)
            
            # Generate secure token
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
            db.session.commit()
            
            # Create reset link
            reset_link = url_for('auth.reset_password', token=token, _external=True)
            
            html = f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
                <h2>Reset Your Password</h2>
                <p>Hello {user.first_name},</p>
                <p>We received a request to reset your password for your Tragene Funded account.</p>
                <p>Click the button below to choose a new password. This link expires in 1 hour.</p>
                <div style="margin: 20px 0;">
                    <a href="{reset_link}"
                       style="
                           background: #3b82f6;
                           color: white;
                           padding: 12px 24px;
                           border-radius: 8px;
                           text-decoration: none;
                           display: inline-block;
                           font-weight: bold;
                       ">
                       Reset Password
                    </a>
                </div>
                <p style="font-size: 12px; color: #666; margin-top: 30px;">
                    If you did not request this, you can safely ignore this email.
                </p>
            </div>
            """
            
            send_test_email(
                user.email,
                "Reset Your Password - Tragene Funded",
                html
            )
            
            # Show remaining reset requests
            reset_data = get_failed_attempts(email, client_ip, 'reset')
            remaining_resets = max(0, MAX_RESET_ATTEMPTS - reset_data.get('count', 0))
            flash(f'Reset email sent! You have {remaining_resets} reset request(s) remaining.', 'success')
        else:
            # Still record attempt to prevent email enumeration
            record_reset_request(email, client_ip)
        
        # Always return the same message to protect user privacy
        flash('If an account exists with this email, a reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))
        
    return render_template('forgot_password.html')

@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Find user with token
    user = User.query.filter_by(reset_token=token).first()
    
    # Reject invalid token
    if not user:
        flash('Invalid or expired reset link.', 'error')
        return redirect(url_for('auth.forgot_password'))
        
    # Check expiry time
    if user.reset_token_expiry and user.reset_token_expiry < datetime.now(timezone.utc):
        flash('Invalid or expired reset link.', 'error')
        return redirect(url_for('auth.forgot_password'))
        
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not password or not confirm_password:
            flash('Both password fields are required.', 'error')
            return render_template('reset_password.html', token=token)
            
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html', token=token)
            
        # Update password securely
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        # Clear any failed attempts for this user
        delete_failed_attempts(user.email, 'login')
        
        flash('Your password has been successfully reset. Please login.', 'success')
        return redirect(url_for('auth.login'))
        
    return render_template('reset_password.html', token=token)