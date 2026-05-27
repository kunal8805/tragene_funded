# ===== COMPLETE WORKING app.py WITH RULE ENGINE & RATE LIMITING (REDIS) =====
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, g
from datetime import datetime, date, timedelta, timezone
import os
import secrets
from functools import wraps
import random
import time
from werkzeug.utils import secure_filename

# ===== ADD RATE LIMITING IMPORTS =====
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    from flask_limiter.errors import RateLimitExceeded
except ImportError:
    # Fallback dummy classes to avoid crash when flask_limiter is not installed
    class Limiter:
        def __init__(self, *args, **kwargs):
            pass
        def error_handler(self, *args, **kwargs):
            pass
    def get_remote_address():
        return "127.0.0.1"
    class RateLimitExceeded(Exception):
        pass

# ===== ADD CASHFREE IMPORTS =====
from cashfree_pg.models.create_order_request import CreateOrderRequest
from cashfree_pg.api_client import Cashfree
from cashfree_pg.models.customer_details import CustomerDetails
from cashfree_pg.models.order_meta import OrderMeta
import hashlib
import hmac
import json
from dotenv import load_dotenv

# ===== ADD FLASK-MIGRATE =====
from flask_migrate import Migrate

# Load environment variables
load_dotenv()

# ===== APP CONFIG FROM ENV =====
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
PRELAUNCH_MODE = False

# ===== REDIS CONFIGURATION =====
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
REDIS_ENABLED = os.getenv('REDIS_ENABLED', 'true').lower() == 'true'

# ===== CASHFREE CONFIGURATION =====
CASHFREE_APP_ID = os.getenv('CASHFREE_APP_ID')
CASHFREE_SECRET_KEY = os.getenv('CASHFREE_SECRET_KEY')
CASHFREE_WEBHOOK_SECRET = os.getenv('CASHFREE_WEBHOOK_SECRET')

if CASHFREE_APP_ID and CASHFREE_SECRET_KEY:
    Cashfree.XClientId = CASHFREE_APP_ID
    Cashfree.XClientSecret = CASHFREE_SECRET_KEY
    Cashfree.XEnvironment = Cashfree.PRODUCTION
    if DEV_MODE:
        print("[OK] Cashfree client initialized")
else:
    if DEV_MODE:
        print("[WARNING] Cashfree keys not set - payment system disabled")

# Import Resend correctly for v2.29.0+
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    if DEV_MODE:
        print("[WARNING] Resend package not installed. Email functionality disabled.")

# Get the current directory and set template path explicitly
current_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(current_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)

# ===== RATE LIMITER CONFIGURATION (PRODUCTION READY) =====
def get_identifier():
    """Get unique identifier for rate limiting (IP + user_id if logged in)"""
    # If user is logged in, use user_id as identifier (prevents user from switching IPs)
    if 'user_id' in session:
        return f"user_{session['user_id']}"
    # Otherwise use IP address
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'

# Configure Redis storage for production
if REDIS_ENABLED and not DEV_MODE:
    try:
        storage_uri = REDIS_URL
        limiter = Limiter(
            key_func=get_identifier,
            app=app,
            default_limits=["200 per day", "50 per hour", "10 per minute"],
            storage_uri=storage_uri,
            strategy="fixed-window",
            storage_options={"socket_connect_timeout": 5},
        )
        if DEV_MODE:
            print("[OK] Redis rate limiter configured")
    except Exception as e:
        print(f"[WARNING] Redis connection failed, falling back to memory: {e}")
        limiter = Limiter(
            key_func=get_identifier,
            app=app,
            default_limits=["200 per day", "50 per hour", "10 per minute"],
            storage_uri="memory://",
            strategy="fixed-window",
        )
else:
    # Development mode - use memory storage
    limiter = Limiter(
        key_func=get_identifier,
        app=app,
        default_limits=["200 per day", "50 per hour", "10 per minute"],
        storage_uri="memory://",
        strategy="fixed-window",
    )
    if DEV_MODE:
        print("[OK] Memory rate limiter configured (development mode)")

# Custom error handler for rate limit exceeded
@app.errorhandler(RateLimitExceeded)
def handle_rate_limit_exceeded(e):
    """Handle rate limit exceeded errors"""
    flash(f"Too many requests. Please slow down. Try again in a moment.", 'error')
    return redirect(url_for('home'))

# ===== SECRET KEY & DATABASE CONFIG =====
app.config['SECRET_KEY'] = os.getenv('APP_SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("APP_SECRET_KEY must be set in .env file")

# Session security - production settings
app.config['SESSION_COOKIE_SECURE'] = not DEV_MODE  # True in production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

db_url = os.getenv('DATABASE_URL', 'sqlite:///tragene_funded_new.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}

if DEV_MODE:
    print(f"[DB] Database: {db_url[:50]}...")

# ===== RESEND CONFIGURATION =====
RESEND_API_KEY = os.getenv('RESEND_API_KEY')

if RESEND_AVAILABLE and RESEND_API_KEY:
    try:
        resend.api_key = RESEND_API_KEY
        if DEV_MODE:
            print("[OK] Resend API key configured successfully")
    except Exception as e:
        print(f"[ERROR] Failed to configure Resend: {e}")
        RESEND_AVAILABLE = False

# File upload configuration
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

# ===== ERROR HANDLERS =====
@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large errors gracefully"""
    flash('Your file is too large. Maximum allowed size is 16MB per file. Please reduce the size and try again.', 'warning')
    if 'user_id' in session:
        return redirect(url_for('user.file_too_large'))
    return redirect(url_for('auth.login'))

@app.errorhandler(500)
def internal_server_error(error):
    """Handle internal server errors"""
    return render_template('500.html'), 500

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    return render_template('404.html'), 404

# ===== INITIALIZE DATABASE & MIGRATE =====
from models import db, User, Notification, ChallengeTemplate, Payment, ChallengePurchase, WebhookLog, FAQ, BlogPost, Coupon, CouponUsage, CouponAssignment

db.init_app(app)
migrate = Migrate(app, db)

# ===== AUTO-CLEANUP EXPIRED NOTIFICATIONS =====
# This hook runs before each request but only performs cleanup once every 24 hours to avoid overhead.
from datetime import datetime, timezone, timedelta

def _cleanup_expired_notifications():
    now = datetime.now(timezone.utc)
    # Find notifications that are not deleted and have expired
    expired_notifications = Notification.query.filter(
        Notification.is_deleted.is_(False),
        Notification.expires_at.isnot(None),
        Notification.expires_at <= now
    ).all()
    if expired_notifications:
        for n in expired_notifications:
            n.is_deleted = True
        db.session.commit()
        if DEV_MODE:
            print(f"[AUTO-CLEANUP] Soft-deleted {len(expired_notifications)} expired notifications")

# Store last cleanup timestamp on the app instance
if not hasattr(app, 'last_notification_cleanup'):
    app.last_notification_cleanup = None

@app.before_request
def before_request_cleanup():
    now = datetime.now(timezone.utc)
    # Perform cleanup if never done or more than 24h ago
    if app.last_notification_cleanup is None or (now - app.last_notification_cleanup) > timedelta(hours=24):
        _cleanup_expired_notifications()
        app.last_notification_cleanup = now

# Custom filter to convert model to dict
@app.template_filter('to_dict')
def to_dict_filter(obj):
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    if isinstance(obj, ChallengeTemplate):
        return {
            'id': obj.id,
            'name': obj.name,
            'price': obj.price,
            'account_size': obj.account_size,
            'phase': obj.phase,
            'phase1_target': obj.phase1_target,
            'phase1_daily_loss': obj.phase1_daily_loss,
            'phase1_overall_loss': obj.phase1_overall_loss,
            'phase1_min_days': obj.phase1_min_days,
            'phase1_duration': obj.phase1_duration,
            'phase1_leverage': obj.phase1_leverage,
            'phase2_target': obj.phase2_target,
            'phase2_daily_loss': obj.phase2_daily_loss,
            'phase2_overall_loss': obj.phase2_overall_loss,
            'phase2_min_days': obj.phase2_min_days,
            'phase2_duration': obj.phase2_duration,
            'phase2_leverage': obj.phase2_leverage,
            'instant_daily_loss': obj.instant_daily_loss,
            'instant_overall_loss': obj.instant_overall_loss,
            'instant_min_days': obj.instant_min_days,
            'instant_leverage': obj.instant_leverage,
            'user_profit_share': obj.user_profit_share,
            'payout_cycle': obj.payout_cycle,
            'weekend_trading': obj.weekend_trading,
            'is_active': obj.is_active,
            'description': obj.description or "",
            'challenge_type': obj.challenge_type or "one_phase",
            'phase1_rules': obj.phase1_rules or "",
            'phase2_rules': obj.phase2_rules or "",
            'instant_rules': obj.instant_rules or ""
        }
    return str(obj)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ===== CONTEXT PROCESSOR FOR TEMPLATES =====
@app.context_processor
def inject_user():
    context = {
        'current_user': None,
        'user': None,
        'PRELAUNCH_MODE': PRELAUNCH_MODE,
        'DEV_MODE': DEV_MODE,
        'datetime': datetime,
        'timezone': timezone
    }

    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            class CurrentUser:
                def __init__(self, user_obj):
                    self.id = user_obj.id
                    self.email = user_obj.email
                    self.first_name = user_obj.first_name
                    self.last_name = user_obj.last_name
                    self.name = f"{user_obj.first_name} {user_obj.last_name}"
                    self.kyc_status = user_obj.kyc_status
                    self.phone_verified = user_obj.phone_verified
                    self.email_verified = user_obj.email_verified
                    self.is_authenticated = True
                    self.is_admin = user_obj.is_admin
                    self.role = 'admin' if user_obj.is_admin else 'user'
                    self.is_active = True
                    
                def __repr__(self):
                    return f"<CurrentUser {self.email}>"
            
            context['current_user'] = CurrentUser(user)
            context['user'] = user
    
    return context

# ===== FIXED EMAIL SENDER FUNCTION =====
def send_test_email(to_email, subject, html_content):
    if not RESEND_AVAILABLE or not resend.api_key:
        if DEV_MODE:
            print("⚠️ Email skipped - Resend not available or API key missing")
        return False
    
    try:
        params = {
            "from": "Tragene Funded <support@tragenefunded.com>",
            "to": [to_email],
            "subject": subject,
            "html": html_content
        }
        result = resend.Emails.send(params)
        if DEV_MODE:
            print(f"✅ Email sent successfully: {result}")
        return True
    except Exception as e:
        print(f"❌ Email failed: {str(e)}")
        return False

# ===== LOGIN DECORATOR =====
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# ===== CASHFREE HELPER FUNCTIONS =====
def verify_cashfree_webhook_signature(payload_body, signature, timestamp):
    if not CASHFREE_WEBHOOK_SECRET:
        print("❌ Cashfree webhook secret not configured")
        return False
        
    try:
        import base64
        data = timestamp + payload_body
        expected_signature_b64 = base64.b64encode(hmac.new(
            CASHFREE_WEBHOOK_SECRET.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).digest()).decode('utf-8')
        
        if signature == expected_signature_b64:
            if DEV_MODE:
                print(f"✅ Webhook signature verified")
            return True
        else:
            print(f"❌ Invalid webhook signature")
            return False
    except Exception as e:
        print(f"❌ Webhook verification error: {e}")
        return False

def get_next_serial_no():
    max_serial = db.session.query(db.func.max(ChallengePurchase.serial_no)).scalar()
    if max_serial is None:
        return 1111
    return max_serial + 1

def generate_challenge_code():
    while True:
        code = str(random.randint(100000, 999999))
        existing = ChallengePurchase.query.filter_by(challenge_code=code).first()
        if not existing:
            return code

def generate_challenge_token():
    while True:
        token = secrets.token_hex(32)
        existing = ChallengePurchase.query.filter_by(challenge_token=token).first()
        if not existing:
            return token

def provision_challenge(payment, user, challenge_template_id):
    """Helper to provision a challenge after successful payment"""
    from models import db, ChallengePurchase, ChallengeTemplate
    
    challenge = ChallengeTemplate.query.get(challenge_template_id)
    if not challenge:
        return False, "Challenge template not found"
        
    if payment.challenge_purchase_id:
        if DEV_MODE:
            print(f"⚠️ Payment {payment.id} already has a challenge assigned: {payment.challenge_purchase_id}")
        return True, payment.challenge_purchase_id
        
    ctype = challenge.challenge_type or 'one_phase'
    initial_status = 'phase1_active'
    initial_phase = 1
    
    if ctype == 'two_phase':
        initial_status = 'phase1_active'
        initial_phase = 1
    elif ctype == 'one_phase':
        initial_status = 'phase1_active'
        initial_phase = 1
    elif ctype == 'instant':
        initial_status = 'funded_active'
        initial_phase = 0
        
    if ctype == 'instant':
        initial_duration = 999
    else:
        initial_duration = challenge.phase1_duration or 30

    purchase = ChallengePurchase(
        user_id=user.id,
        challenge_template_id=challenge.id,
        purchase_date=datetime.now(timezone.utc),
        amount=challenge.price,
        payment_method='cashfree',
        status=initial_status,
        challenge_type=ctype,
        current_phase=initial_phase,
        is_terminated=False,
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc) + timedelta(days=initial_duration),
        mt5_account=f"TRG_{user.id}_{challenge.id}_{datetime.now().strftime('%Y%m%d')}",
        current_profit=0.0,
        current_loss=0.0,
        phase=initial_phase,
        progress_percentage=0.0,
        days_remaining=initial_duration
    )
    
    # ===== RULE ENGINE FIELD INITIALIZATION =====
    purchase.starting_balance = float(challenge.account_size)
    purchase.starting_equity = float(challenge.account_size)
    purchase.current_balance = float(challenge.account_size)
    purchase.current_equity = float(challenge.account_size)
    purchase.peak_equity = float(challenge.account_size)
    purchase.highest_equity = float(challenge.account_size)
    purchase.day_start_equity = float(challenge.account_size)
    purchase.lowest_equity_today = float(challenge.account_size)
    purchase.highest_equity_today = float(challenge.account_size)
    purchase.daily_start_date = datetime.now(timezone.utc).date()
    purchase.profit_percent = 0.0
    purchase.daily_drawdown = 0.0
    purchase.overall_drawdown = 0.0
    purchase.trading_days = 0
    purchase.risk_score = 0
    purchase.monitoring_status = 'active'
    purchase.review_required = False
    purchase.phase1_completed_at = None
    purchase.phase2_started_at = None
    purchase.funded_at = None
    purchase.phase_start_balance = float(challenge.account_size)
    purchase.phase_start_equity = float(challenge.account_size)
    purchase.phase_start_date = datetime.now(timezone.utc)
    purchase.phase_trading_days = 0
    purchase.phase_profit_percent = 0.0
    purchase.phase_daily_drawdown = 0.0
    purchase.phase_day_start_equity = float(challenge.account_size)
    purchase.phase_lowest_equity_today = float(challenge.account_size)
    purchase.phase_daily_start_date = datetime.now(timezone.utc).date()
    purchase.distance_to_payout = None
    purchase.distance_to_breach = None
    purchase.last_trade_date = None
    
    purchase.serial_no = get_next_serial_no()
    purchase.challenge_code = generate_challenge_code()
    purchase.challenge_token = generate_challenge_token()
    
    db.session.add(purchase)
    db.session.flush()
    payment.challenge_purchase_id = purchase.id
    
    # ===== PARTNER REVENUE SHARE LOGIC =====
    from models import PartnerEarnings
    partner = User.query.filter_by(role='partner', is_banned=False).first()
    if partner:
        earning = PartnerEarnings(
            partner_id=partner.id,
            challenge_id=challenge.id,
            user_id=user.id,
            purchase_amount=float(challenge.price),
            partner_share=round(float(challenge.price) * 0.20, 2),
            purchased_at=datetime.now(timezone.utc)
        )
        db.session.add(earning)
        if DEV_MODE:
            print(f"[OK] Added 20% partner revenue share for {partner.email}")
    
    if DEV_MODE:
        print(f"[OK] Challenge purchase created: {purchase.id}")
        print(f"[OK] Rule engine fields initialized with account size: {challenge.account_size}")
        
    return True, purchase.id

# ===== SEED DEFAULT DATA =====
with app.app_context():
    db.create_all()
    
    try:
        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")

        if not admin_email or not admin_password:
            raise ValueError("ADMIN_EMAIL and ADMIN_PASSWORD must be set in .env")

        if not User.query.filter_by(email=admin_email).first():
            admin = User(
                first_name="Tragene",
                last_name="Admin",
                email=admin_email,
                phone="0000000000",
                dob=date(1990, 1, 1),
                country="India",
                state="Maharashtra",
                is_admin=True,
                phone_verified=True,
                email_verified=True,
                kyc_status='approved'
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            if DEV_MODE:
                print(f"[OK] Default admin created: {admin_email}")

        # ===== SEED PARTNER ACCOUNT =====
        partner_email = os.getenv("PARTNER_EMAIL")
        partner_password = os.getenv("PARTNER_PASSWORD")
        if partner_email and partner_password:
            if not User.query.filter_by(email=partner_email).first():
                partner = User(
                    first_name="Tragene",
                    last_name="Partner",
                    email=partner_email,
                    phone="1111111111",
                    dob=date(1990, 1, 1),
                    country="India",
                    state="Maharashtra",
                    role="partner",
                    is_banned=False,
                    phone_verified=True,
                    email_verified=True,
                    kyc_status='approved'
                )
                partner.set_password(partner_password)
                db.session.add(partner)
                db.session.commit()
                if DEV_MODE:
                    print(f"[OK] Default partner created: {partner_email}")
            else:
                # Ensure existing partner account has correct role
                existing_partner = User.query.filter_by(email=partner_email).first()
                if existing_partner and existing_partner.role != 'partner':
                    existing_partner.role = 'partner'
                    db.session.commit()
                    if DEV_MODE:
                        print(f"[OK] Updated partner role for: {partner_email}")

        if not ChallengeTemplate.query.first():
            default_challenges = [
                ChallengeTemplate(name="Basic Challenge", price=99, account_size=100, phase=1, phase1_target=8.0, phase1_daily_loss=5.0, phase1_overall_loss=10.0, phase1_min_days=5, phase1_duration=30, phase1_leverage="1:100", challenge_type="one_phase", user_profit_share=80, payout_cycle="biweekly", weekend_trading=True, is_active=True, description="Start your trading journey"),
                ChallengeTemplate(name="Advanced Challenge", price=149, account_size=150, phase=1, phase1_target=8.0, phase1_daily_loss=5.0, phase1_overall_loss=10.0, phase1_min_days=5, phase1_duration=30, phase1_leverage="1:100", challenge_type="one_phase", user_profit_share=85, payout_cycle="biweekly", weekend_trading=True, is_active=True, description="Advanced challenge"),
                ChallengeTemplate(name="Pro Challenge", price=199, account_size=200, phase=1, phase1_target=8.0, phase1_daily_loss=5.0, phase1_overall_loss=10.0, phase1_min_days=5, phase1_duration=30, phase1_leverage="1:100", challenge_type="one_phase", user_profit_share=90, payout_cycle="biweekly", weekend_trading=True, is_active=True, description="Pro challenge")
            ]
            for challenge in default_challenges:
                db.session.add(challenge)
            db.session.commit()
            if DEV_MODE:
                print("[OK] Default challenge templates created")
    except Exception as e:
        if DEV_MODE:
            print(f"[INFO] DB not ready for seeding: {e}")

    # ===== BACKFILL PARTNER EARNINGS FOR PAST PURCHASES =====
    try:
        from models import PartnerEarnings
        partner = User.query.filter_by(role='partner', is_banned=False).first()
        if partner:
            # Find all purchases that don't have a matching PartnerEarnings record
            existing_purchase_ids = db.session.query(PartnerEarnings.user_id, PartnerEarnings.challenge_id).filter_by(partner_id=partner.id).all()
            existing_set = set((r[0], r[1]) for r in existing_purchase_ids)
            
            all_purchases = ChallengePurchase.query.all()
            backfilled = 0
            for purchase in all_purchases:
                key = (purchase.user_id, purchase.challenge_id)
                if key not in existing_set:
                    challenge = ChallengeTemplate.query.get(purchase.challenge_id)
                    if challenge:
                        earning = PartnerEarnings(
                            partner_id=partner.id,
                            challenge_id=challenge.id,
                            user_id=purchase.user_id,
                            purchase_amount=float(challenge.price),
                            partner_share=round(float(challenge.price) * 0.20, 2),
                            purchased_at=purchase.purchased_at or datetime.now(timezone.utc)
                        )
                        db.session.add(earning)
                        backfilled += 1
            if backfilled > 0:
                db.session.commit()
                if DEV_MODE:
                    print(f"[OK] Backfilled {backfilled} partner earnings for past purchases")
            elif DEV_MODE:
                print("[OK] Partner earnings up to date - no backfill needed")
    except Exception as e:
        if DEV_MODE:
            print(f"[INFO] Partner earnings backfill skipped: {e}")

    # Register blueprints individually for robustness
    blueprints_to_load = [
        ('auth', 'auth_bp'),
        ('admin_routes', 'admin_bp'),
        ('user_routes', 'user_bp'),
        ('blog', 'blog_bp'),
        ('admin_blog', 'admin_blog_bp'),
        ('mt5_receiver', 'receiver_bp'),
        ('partner_routes', 'partner_bp')
    ]
    
    for module_name, bp_name in blueprints_to_load:
        try:
            module = __import__(module_name, fromlist=[bp_name])
            bp = getattr(module, bp_name)
            app.register_blueprint(bp)
            if DEV_MODE:
                print(f"[OK] Registered blueprint: {bp_name}")
        except Exception as e:
            import traceback
            print(f"[WARNING] Failed to register blueprint {bp_name} from {module_name}: {e}")
            traceback.print_exc()

# ===== CASHFREE PAYMENT ROUTES =====
@app.route('/create-cashfree-order', methods=['POST'])
@login_required
@limiter.limit("10 per minute", key_func=lambda: f"payment_{session.get('user_id', 'unknown')}")
def create_cashfree_order():
    if not CASHFREE_APP_ID:
        return jsonify({'success': False, 'error': 'Payment system not configured'})
    
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'success': False, 'error': 'User not found'})
        
        challenge_id = request.form.get('challenge_id')
        if not challenge_id:
            return jsonify({'success': False, 'error': 'Challenge ID required'})
        
        challenge = ChallengeTemplate.query.get(challenge_id)
        if not challenge:
            return jsonify({'success': False, 'error': 'Challenge not found'})
        
        if user.kyc_status != 'approved':
            return jsonify({'success': False, 'error': 'Please complete KYC verification first'})
        
        coupon_code = request.form.get('coupon_code')
        coupon_id = None
        expected_payable_amount = float(challenge.price)
        
        if coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code.upper().strip(), is_deleted=False).first()
            if not coupon:
                return jsonify({'success': False, 'error': 'Invalid coupon code'})
            
            is_valid, msg, discount_amount, final_price = coupon.validate_for_user_and_price(user.id, expected_payable_amount)
            if not is_valid:
                return jsonify({'success': False, 'error': msg})
                
            expected_payable_amount = final_price
            coupon_id = coupon.id
            
        internal_order_id = f"ORDER_{user.id}_{int(time.time())}_{secrets.token_hex(4)}"
        
        customer_details = CustomerDetails(
            customer_id=f"USER_{user.id}",
            customer_phone=user.phone or "9999999999",
            customer_email=user.email,
            customer_name=f"{user.first_name} {user.last_name}"
        )
        
        order_meta = OrderMeta(
            return_url=f"https://www.tragenefunded.com/payment-success?order_id={internal_order_id}",
            notify_url="https://www.tragenefunded.com/cashfree-webhook"
        )
        
        # DEBUG: Check the amount type before sending
        print(f"[DEBUG] order_amount type={type(expected_payable_amount)}, value={expected_payable_amount!r}")
        
        create_order_request = CreateOrderRequest(
            order_amount=expected_payable_amount,
            order_currency="INR",
            order_id=internal_order_id,
            customer_details=customer_details,
            order_meta=order_meta,
            order_note=f"Challenge: {challenge.name}"
        )
        
        api_response = Cashfree().PGCreateOrder(x_api_version="2023-08-01", create_order_request=create_order_request)
        order_response = api_response.data
        
        if DEV_MODE:
            print(f"[OK] Cashfree Order Created: {internal_order_id} for INR {expected_payable_amount}")
        
        payment = Payment(
            user_id=user.id,
            challenge_template_id=challenge.id,
            payment_id=internal_order_id,
            amount=expected_payable_amount,
            expected_amount=expected_payable_amount,
            currency='INR',
            payment_method='cashfree',
            status='pending',
            gateway='cashfree',
            gateway_id='',
            coupon_id=coupon_id,
            gateway_response=json.dumps({'payment_session_id': order_response.payment_session_id})
        )
        
        db.session.add(payment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'payment_session_id': order_response.payment_session_id,
            'order_id': internal_order_id
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Create order error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cashfree-webhook', methods=['POST'])
def cashfree_webhook():
    try:
        from models import WebhookLog, Payment, db
        payload = request.get_data().decode('utf-8')
        signature = request.headers.get('x-webhook-signature')
        timestamp = request.headers.get('x-webhook-timestamp')
        
        if not signature or not timestamp:
            return jsonify({'status': 'ok'}), 200
            
        if not verify_cashfree_webhook_signature(payload, signature, timestamp):
            return jsonify({'status': 'invalid signature'}), 401
            
        data = json.loads(payload)
        event_type = data.get('type')
        order_id = data.get('data', {}).get('order', {}).get('order_id')
        
        webhook_log = WebhookLog(
            event_type=event_type,
            order_id=order_id,
            raw_payload=payload,
            headers=json.dumps(dict(request.headers)),
            signature=signature,
            status='pending'
        )
        db.session.add(webhook_log)
        db.session.commit()
        
        if event_type == 'PAYMENT_SUCCESS_WEBHOOK':
            payment_info = data.get('data', {}).get('payment', {})
            cf_payment_id = payment_info.get('cf_payment_id')
            paid_amount = float(payment_info.get('payment_amount', 0))
            payment_currency = payment_info.get('payment_currency')
            
            payment = Payment.query.with_for_update().filter_by(payment_id=order_id).first()
            if not payment:
                webhook_log.status = 'failed'
                webhook_log.error_message = 'Payment record not found'
                db.session.commit()
                return jsonify({'status': 'order not found'}), 200
                
            if payment.status in ['paid', 'success']:
                webhook_log.status = 'duplicate'
                db.session.commit()
                return jsonify({'status': 'already processed'}), 200
                
            if paid_amount != payment.expected_amount:
                payment.status = 'failed'
                webhook_log.status = 'failed'
                webhook_log.error_message = f'Amount mismatch. Expected {payment.expected_amount}, got {paid_amount}'
                db.session.commit()
                return jsonify({'status': 'amount mismatch'}), 200
                
            if payment_currency != 'INR':
                payment.status = 'failed'
                webhook_log.status = 'failed'
                webhook_log.error_message = 'Currency mismatch'
                db.session.commit()
                return jsonify({'status': 'currency mismatch'}), 200
                
            try:
                api_response = Cashfree().PGOrderFetchPayments(x_api_version="2023-08-01", order_id=order_id)
                payments_list = api_response.data
                
                is_actually_paid = False
                for p in payments_list:
                    if str(p.cf_payment_id) == str(cf_payment_id) and p.payment_status == 'SUCCESS':
                        is_actually_paid = True
                        break
                        
                if not is_actually_paid:
                    webhook_log.status = 'failed'
                    webhook_log.error_message = 'Direct API verification failed'
                    db.session.commit()
                    return jsonify({'status': 'api verification failed'}), 200
            except Exception as e:
                print(f"Direct verification error: {e}")
                return jsonify({'status': 'error verifying with API'}), 500
                
            user = User.query.get(payment.user_id)
            success, msg = provision_challenge(payment, user, payment.challenge_template_id)
            
            if success:
                payment.status = 'success'
                payment.gateway_id = str(cf_payment_id)
                payment.gateway_response = json.dumps(data)
                webhook_log.status = 'processed'
                webhook_log.processed_at = datetime.now(timezone.utc)
                
                # Consume coupon if any associated with payment
                if payment.coupon_id:
                    coupon = Coupon.query.with_for_update().get(payment.coupon_id)
                    if coupon:
                        coupon.used_count += 1
                        
                        # Mark assignment as used if specific
                        if coupon.coupon_type == 'specific':
                            assignment = CouponAssignment.query.filter_by(
                                coupon_id=coupon.id,
                                user_id=payment.user_id,
                                is_used=False
                            ).first()
                            if assignment:
                                assignment.is_used = True
                        
                        # Calculate pricing
                        original_price = float(payment.challenge_purchase.challenge_template.price) if payment.challenge_purchase and payment.challenge_purchase.challenge_template else float(payment.amount)
                        discount_amount = max(0.0, original_price - float(payment.amount))
                        
                        # Create CouponUsage record
                        usage = CouponUsage(
                            coupon_id=coupon.id,
                            user_id=payment.user_id,
                            challenge_purchase_id=payment.challenge_purchase_id,
                            original_price=original_price,
                            discount_amount=discount_amount,
                            final_price=float(payment.amount),
                            used_at=datetime.now(timezone.utc)
                        )
                        db.session.add(usage)
            else:
                payment.status = 'failed'
                webhook_log.status = 'failed'
                webhook_log.error_message = f'Provisioning failed: {msg}'
                
            db.session.commit()
            return jsonify({'status': 'success'}), 200
            
        elif event_type == 'PAYMENT_FAILED_WEBHOOK':
            payment = Payment.query.filter_by(payment_id=order_id).first()
            if payment and payment.status == 'pending':
                payment.status = 'failed'
                payment.gateway_response = json.dumps(data)
                webhook_log.status = 'processed'
                db.session.commit()
            return jsonify({'status': 'recorded failure'}), 200
            
        else:
            webhook_log.status = 'ignored'
            db.session.commit()
            return jsonify({'status': 'event ignored'}), 200
            
    except Exception as e:
        print(f"Webhook processing error: {e}")
        return jsonify({'status': 'error'}), 500
    





@app.route('/api/coupons/new-count')
@login_required
def api_coupon_new_count():
    from datetime import datetime, timedelta
    
    # Count recent coupons - adjust logic as needed
    count = 0
    if current_user.is_authenticated:
        # Example: count all active coupons
        # Replace with your actual Coupon model and logic
        try:
            from models import Coupon  # Adjust import based on your project
            count = Coupon.query.filter(
                Coupon.is_active == True
            ).count()
        except:
            # Fallback - just return a test count for now
            count = 5  # Remove this after testing
    
    return jsonify({'new_count': count})




@app.route('/payment-success')
@login_required
def payment_success():
    order_id = request.args.get('order_id')
    if not order_id:
        flash('Invalid order reference', 'error')
        return redirect(url_for('user.challenges'))
        
    payment = Payment.query.filter_by(payment_id=order_id).first()
    if not payment:
        flash('Payment not found', 'error')
        return redirect(url_for('user.challenges'))
        
    if payment.user_id != session.get('user_id'):
        flash('Access denied', 'error')
        return redirect(url_for('user.dashboard'))
        
    if payment.status == 'pending':
        flash('Your payment is being verified securely. Please check back in a moment.', 'info')
        return redirect(url_for('payment_status', payment_id=payment.id))
        
    elif payment.status == 'success' or payment.status == 'paid':
        flash('Payment successful! Your account has been created.', 'success')
        return redirect(url_for('payment_status', payment_id=payment.id))
        
    else:
        flash('❌ Payment failed or invalid. Please try again.', 'error')
        return redirect(url_for('payment_status', payment_id=payment.id))

@app.route('/payment/status/<int:payment_id>')
@login_required
def payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    
    current_user = User.query.get(session.get('user_id'))
    if payment.user_id != session.get('user_id') and not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('user.dashboard'))
    
    challenge_purchase = None
    if payment.challenge_purchase_id:
        challenge_purchase = ChallengePurchase.query.get(payment.challenge_purchase_id)
    
    return render_template('user/payment_status.html',
                         payment=payment,
                         challenge=challenge_purchase,
                         status=payment.status,
                         user=current_user)

@app.route('/payment/failed')
@login_required
def payment_failed():
    return render_template('user/payment_failed.html', user=User.query.get(session['user_id']))

# ===== RULE ENGINE API ENDPOINTS =====

@app.route('/api/challenge/<int:challenge_id>/metrics')
@login_required
def get_challenge_metrics(challenge_id):
    """API endpoint for dashboard to get real-time metrics"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    challenge = ChallengePurchase.query.filter_by(id=challenge_id).first()
    
    if not challenge:
        return jsonify({'error': 'Challenge not found'}), 404
    
    if challenge.user_id != user_id and not user.is_admin:
        return jsonify({'error': 'Access denied'}), 403
    
    def safe_round(value, decimals=2):
        if value is None:
            return None
        try:
            return round(float(value), decimals)
        except (TypeError, ValueError):
            return None
    
    return jsonify({
        'success': True,
        'challenge_id': challenge.id,
        'challenge_name': challenge.challenge_template.name if challenge.challenge_template else 'N/A',
        'metrics': {
            'profit_percent': safe_round(challenge.profit_percent, 2),
            'phase_profit_percent': safe_round(challenge.phase_profit_percent, 2),
            'daily_drawdown': safe_round(challenge.daily_drawdown, 2),
            'overall_drawdown': safe_round(challenge.overall_drawdown, 2),
            'trading_days': challenge.trading_days or 0,
            'phase_trading_days': challenge.phase_trading_days or 0,
            'days_remaining': challenge.days_remaining or 0,
            'distance_to_payout': safe_round(challenge.distance_to_payout, 2),
            'distance_to_breach': safe_round(challenge.distance_to_breach, 2),
            'risk_score': challenge.risk_score or 0,
            'status': challenge.status or 'unknown',
            'monitoring_status': challenge.monitoring_status or 'unknown',
            'current_balance': safe_round(challenge.current_balance, 2),
            'current_equity': safe_round(challenge.current_equity, 2),
            'progress_percentage': safe_round(challenge.progress_percentage, 1)
        }
    })

@app.route('/api/challenge/<int:challenge_id>/rules')
@login_required
def get_challenge_rules_api(challenge_id):
    """Get current challenge rules for display"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    challenge = ChallengePurchase.query.filter_by(id=challenge_id).first()
    
    if not challenge:
        return jsonify({'error': 'Challenge not found'}), 404
    
    if challenge.user_id != user_id and not user.is_admin:
        return jsonify({'error': 'Access denied'}), 403
    
    template = challenge.challenge_template
    if not template:
        return jsonify({'error': 'Template not found'}), 404
    
    if challenge.challenge_type == 'two_phase' and challenge.current_phase == 2:
        rules = {
            'phase': 'Phase 2',
            'profit_target': template.phase2_target,
            'daily_loss': template.phase2_daily_loss,
            'overall_loss': template.phase2_overall_loss,
            'min_trading_days': template.phase2_min_days,
            'duration': template.phase2_duration,
            'leverage': template.phase2_leverage
        }
    elif challenge.challenge_type == 'instant':
        rules = {
            'phase': 'Instant Funded',
            'profit_target': 0,
            'daily_loss': template.instant_daily_loss,
            'overall_loss': template.instant_overall_loss,
            'min_trading_days': template.instant_min_days,
            'duration': 365,
            'leverage': template.instant_leverage
        }
    else:
        rules = {
            'phase': 'Phase 1',
            'profit_target': template.phase1_target,
            'daily_loss': template.phase1_daily_loss,
            'overall_loss': template.phase1_overall_loss,
            'min_trading_days': template.phase1_min_days,
            'duration': template.phase1_duration,
            'leverage': template.phase1_leverage
        }
    
    return jsonify({
        'success': True,
        'challenge_type': challenge.challenge_type,
        'current_phase': challenge.current_phase,
        'rules': rules
    })

@app.route('/api/user/challenges/metrics')
@login_required
def get_user_all_challenges_metrics():
    """Get metrics for all user's active challenges"""
    user_id = session.get('user_id')
    
    challenges = ChallengePurchase.query.filter_by(user_id=user_id).all()
    
    def safe_round(value, decimals=2):
        if value is None:
            return None
        try:
            return round(float(value), decimals)
        except (TypeError, ValueError):
            return None
    
    result = []
    for challenge in challenges:
        result.append({
            'id': challenge.id,
            'challenge_name': challenge.challenge_template.name if challenge.challenge_template else 'N/A',
            'profit_percent': safe_round(challenge.profit_percent, 2),
            'daily_drawdown': safe_round(challenge.daily_drawdown, 2),
            'overall_drawdown': safe_round(challenge.overall_drawdown, 2),
            'distance_to_payout': safe_round(challenge.distance_to_payout, 2),
            'distance_to_breach': safe_round(challenge.distance_to_breach, 2),
            'status': challenge.status or 'unknown',
            'days_remaining': challenge.days_remaining or 0
        })
    
    return jsonify({
        'success': True,
        'challenges': result
    })

# ===== MAIN ROUTES =====
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/faq')
def faq():
    faqs = FAQ.query.order_by(FAQ.is_pinned.desc(), FAQ.created_at.desc()).all()
    categories = {}
    for faq in faqs:
        if faq.category not in categories:
            categories[faq.category] = []
        categories[faq.category].append(faq)
    return render_template('faq.html', categories=categories)

@app.route('/help')
def help_center():
    flash('Please login to access the Help Center and Ticket system.', 'info')
    return redirect(url_for('auth.login'))

@app.route('/refund-policy')
def refund_policy():
    return render_template('refund.html')

# ===== MAIN =====
if __name__ == '__main__':
    print("\n" + "="*60)
    print("TRAGENE FUNDED SERVER")
    print("="*60)
    print(f"Environment: {'DEVELOPMENT' if DEV_MODE else 'PRODUCTION'}")
    
    if DEV_MODE:
        print(f"Database: {db_url[:60]}...")
        print(f"Template folder: {app.template_folder}")
        print(f"Resend: {'ENABLED' if RESEND_AVAILABLE else 'DISABLED'}")
        cashfree_enabled = bool(CASHFREE_APP_ID and CASHFREE_SECRET_KEY)
        print(f"Cashfree: {'ENABLED' if cashfree_enabled else 'DISABLED'}")
        print(f"Redis: {'ENABLED' if REDIS_ENABLED else 'DISABLED'}")
        important_templates = ['index.html', 'user/user_dashboard.html', 'login.html', 
                              'user/payment_status.html', 'user/payment_failed.html']
        for template in important_templates:
            template_path = os.path.join(app.template_folder, template)
            status = "OK" if os.path.exists(template_path) else "MISS"
            print(f"  [{status}] {template}")
    
    print("="*60 + "\n")
    
    # Use production WSGI server for production
    if not DEV_MODE:
        print("⚠️  For production, use a production WSGI server like Gunicorn or Waitress")
        print("   Example: waitress-serve --host=0.0.0.0 --port=5003 app:app")
    
    app.run(debug=DEV_MODE, host='0.0.0.0', port=5003)