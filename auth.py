from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timezone, timedelta
import secrets
import random
from functools import wraps
from models import db, User
from app import send_test_email


auth_bp = Blueprint('auth', __name__)

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
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password) and not user.is_banned:
            session.clear()
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['user_name'] = f"{user.first_name} {user.last_name}"
            session['is_admin'] = user.is_admin
            session.permanent = True
            flash(f'Welcome back, {user.first_name}!', 'success')
            return redirect(url_for('admin.admin_dashboard') if user.is_admin else url_for('user.dashboard'))
        elif user and user.is_banned:
            flash('Your account has been banned.', 'error')
        else:
            flash('Invalid email or password.', 'error')
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
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Generate secure token
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
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
                "Reset Your Password",
                html
            )
            
        # Always return the same message to protect user privacy
        flash('If an account exists, a reset email has been sent.', 'success')
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
    if user.reset_token_expiry and user.reset_token_expiry < datetime.utcnow():
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
        
        flash('Your password has been successfully reset. Please login.', 'success')
        return redirect(url_for('auth.login'))
        
    return render_template('reset_password.html', token=token)