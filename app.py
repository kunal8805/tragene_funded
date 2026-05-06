# ===== COMPLETE WORKING app.py WITH RAZORPAY =====
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, g
from datetime import datetime, date, timedelta, timezone
import os
import secrets
from functools import wraps
import random
import time
from werkzeug.utils import secure_filename

# ===== ADD RAZORPAY IMPORTS =====
import razorpay
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
PRELAUNCH_MODE = os.getenv("PRELAUNCH_MODE", "true").lower() == "true"

# ===== RAZORPAY CONFIGURATION =====
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET')

if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    if DEV_MODE:
        print("✅ Razorpay client initialized")
else:
    razorpay_client = None
    if DEV_MODE:
        print("⚠️ Razorpay keys not set - payment system disabled")

# Import Resend correctly for v2.19.0
try:
    from resend import Resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    if DEV_MODE:
        print("[WARNING] Resend package not installed. Email functionality disabled.")

# Get the current directory and set template path explicitly
current_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(current_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)

# ===== SECRET KEY & DATABASE CONFIG =====
app.config['SECRET_KEY'] = os.getenv('APP_SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("❌ APP_SECRET_KEY must be set in .env file")

# Session security
app.config['SESSION_COOKIE_SECURE'] = not DEV_MODE  # HTTPS only in production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

db_url = os.getenv('DATABASE_URL', 'sqlite:///tragene_funded_new.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

if DEV_MODE:
    print(f"🗄️ Database: {db_url[:50]}...")

# ===== RESEND CONFIGURATION =====
RESEND_API_KEY = os.getenv('RESEND_API_KEY')
TEST_EMAIL = os.getenv('TEST_EMAIL', 'dhadekunal11@gmail.com')

# Initialize Resend client ONLY if available
if RESEND_AVAILABLE and RESEND_API_KEY:
    try:
        client = Resend(api_key=RESEND_API_KEY)
        if DEV_MODE:
            print("✅ Resend client initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize Resend: {e}")
        client = None
        RESEND_AVAILABLE = False
else:
    client = None

# File upload configuration
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

# ===== INITIALIZE DATABASE & MIGRATE =====
from models import db, User, ChallengeTemplate, Payment, ChallengePurchase, WaitlistLead

db.init_app(app)
migrate = Migrate(app, db)

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
            'profit_target': obj.profit_target,
            'max_daily_loss': obj.max_daily_loss,
            'max_overall_loss': obj.max_overall_loss,
            'min_trading_days': obj.min_trading_days,
            'duration_days': obj.duration_days,
            'leverage': obj.leverage,
            'user_profit_share': obj.user_profit_share,
            'payout_cycle': obj.payout_cycle,
            'weekend_trading': obj.weekend_trading,
            'is_active': obj.is_active,
            'description': obj.description or ""
        }
    return str(obj)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ===== CONTEXT PROCESSOR FOR TEMPLATES =====
@app.context_processor
def inject_user():
    """Make user available in all templates as both 'user' and 'current_user'"""
    user = None
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
                self.is_active = True
                
            def __repr__(self):
                return f"<CurrentUser {self.email}>"
        
        return dict(current_user=CurrentUser(user), user=user)
    
    return dict(current_user=None, user=None)

# ===== FIXED EMAIL SENDER FUNCTION =====
def send_test_email(to_email, subject, html_content):
    if not RESEND_AVAILABLE or client is None:
        if DEV_MODE:
            print("⚠️ Email skipped - Resend not available")
        return True
    
    try:
        params = {
            "from": "Tragene Funded <onboarding@resend.dev>",
            "to": [TEST_EMAIL],
            "subject": f"[TEST] {subject}",
            "html": f"""
            <div style='font-family: Arial;'>
                <strong>TEST EMAIL</strong><br>
                Original recipient: {to_email}<br><br>
                {html_content}
            </div>
            """
        }

        result = client.emails.send(params)
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

# ===== RAZORPAY HELPER FUNCTIONS =====
def verify_razorpay_payment(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """Verify Razorpay payment signature"""
    if not RAZORPAY_KEY_SECRET:
        print("❌ Razorpay secret not configured")
        return False
    
    try:
        body = f"{razorpay_order_id}|{razorpay_payment_id}"
        expected_signature = hmac.new(
            RAZORPAY_KEY_SECRET.encode(),
            body.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if razorpay_signature == expected_signature:
            if DEV_MODE:
                print(f"✅ Payment verified: {razorpay_payment_id}")
            return True
        else:
            print(f"❌ Invalid signature for payment: {razorpay_payment_id}")
            return False
            
    except Exception as e:
        print(f"❌ Payment verification error: {e}")
        return False

# ===== SEED DEFAULT DATA =====
with app.app_context():
    try:
        admin_email = os.getenv("ADMIN_EMAIL", "admin@tragene.com")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

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
                print(f"✅ Default admin created: {admin_email}")

        if not ChallengeTemplate.query.first():
            default_challenges = [
                ChallengeTemplate(name="Basic Challenge", price=99, account_size=50, phase=1, profit_target=12.0, max_daily_loss=5.0, max_overall_loss=8.0, min_trading_days=4, duration_days=30, leverage="1:100", user_profit_share=70, payout_cycle="biweekly", weekend_trading=True, is_active=True, description="Start your trading journey"),
                ChallengeTemplate(name="Advanced Challenge", price=149, account_size=75, phase=1, profit_target=12.0, max_daily_loss=5.0, max_overall_loss=8.0, min_trading_days=5, duration_days=30, leverage="1:100", user_profit_share=75, payout_cycle="biweekly", weekend_trading=True, is_active=True, description="Advanced challenge"),
                ChallengeTemplate(name="Pro Challenge", price=199, account_size=100, phase=1, profit_target=12.0, max_daily_loss=5.0, max_overall_loss=8.0, min_trading_days=4, duration_days=30, leverage="1:100", user_profit_share=70, payout_cycle="biweekly", weekend_trading=True, is_active=True, description="Pro challenge")
            ]

            for challenge in default_challenges:
                db.session.add(challenge)
            db.session.commit()
            if DEV_MODE:
                print("✅ Default challenge templates created")
    except Exception as e:
        if DEV_MODE:
            print(f"[INFO] DB not ready for seeding: {e}")

    # Register blueprints
    try:
        from auth import auth_bp
        from admin_routes import admin_bp
        from user_routes import user_bp

        app.register_blueprint(auth_bp)
        app.register_blueprint(admin_bp)
        app.register_blueprint(user_bp)
        if DEV_MODE:
            print("[OK] Blueprints registered successfully")
    except ImportError as e:
        print(f"[WARNING] Some blueprints not found: {e}")

# ===== RAZORPAY PAYMENT ROUTES =====
@app.route('/create-razorpay-order', methods=['POST'])
@login_required
def create_razorpay_order():
    """Create Razorpay order when user clicks 'Proceed to Payment'"""
    if not razorpay_client:
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
        
        notes = {
            'user_id': str(user.id),
            'challenge_id': str(challenge.id),
            'challenge_name': challenge.name,
            'account_size': str(challenge.account_size)
        }
        
        amount_in_paise = int(challenge.price * 100)
        order_data = {
            'amount': amount_in_paise,
            'currency': 'INR',
            'payment_capture': 1,
            'notes': notes
        }
        
        order = razorpay_client.order.create(data=order_data)
        if DEV_MODE:
            print(f"✅ Razorpay Order Created: {order['id']} for ₹{challenge.price}")
        
        payment = Payment(
            user_id=user.id,
            payment_id=order['id'],
            amount=challenge.price,
            currency='INR',
            payment_method='razorpay',
            status='pending',
            gateway_id='',
            gateway_response=json.dumps({'order_id': order['id']})
        )
        
        db.session.add(payment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'order_id': order['id'],
            'amount': challenge.price,
            'amount_in_paise': amount_in_paise,
            'currency': 'INR',
            'key': RAZORPAY_KEY_ID,
            'name': 'Tragene Funded',
            'description': f'{challenge.name} - ${challenge.account_size} Account',
            'user': {
                'name': f'{user.first_name} {user.last_name}',
                'email': user.email,
                'phone': user.phone
            },
            'prefill': {
                'name': f'{user.first_name} {user.last_name}',
                'email': user.email,
                'contact': user.phone
            },
            'notes': notes
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Create order error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/verify-payment', methods=['POST'])
@login_required
def verify_payment():
    """Verify payment after Razorpay redirect"""
    if not razorpay_client:
        flash('Payment system not configured', 'error')
        return redirect(url_for('user.challenges'))
    
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        if not user:
            flash('User not found', 'error')
            return redirect(url_for('auth.login'))
        
        razorpay_order_id = request.form.get('razorpay_order_id')
        razorpay_payment_id = request.form.get('razorpay_payment_id')
        razorpay_signature = request.form.get('razorpay_signature')
        challenge_id = request.form.get('challenge_id')
        
        if DEV_MODE:
            print(f"\n🔍 Payment Verification: {user.email}")
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            flash('Invalid payment response', 'error')
            return redirect(url_for('user.challenges'))
        
        is_valid = verify_razorpay_payment(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature
        )
        
        if not is_valid:
            flash('Payment verification failed. Possible fraud attempt.', 'error')
            return redirect(url_for('user.challenges'))
        
        try:
            payment_details = razorpay_client.payment.fetch(razorpay_payment_id)
        except Exception as e:
            print(f"❌ Error fetching payment: {e}")
            payment_details = {'status': 'captured'}
        
        payment = Payment.query.filter_by(payment_id=razorpay_order_id).first()
        
        if not payment:
            payment = Payment(
                user_id=user.id,
                payment_id=razorpay_order_id,
                amount=0,
                currency='INR',
                payment_method='razorpay',
                status='pending',
                gateway_id=razorpay_payment_id,
                gateway_response=json.dumps(payment_details)
            )
        
        if payment.status == 'success':
            flash('Payment already verified.', 'info')
            return redirect(url_for('user.payment_status', payment_id=payment.id))
        
        payment.status = 'success' if payment_details.get('status') == 'captured' else 'failed'
        payment.gateway_id = razorpay_payment_id
        payment.gateway_response = json.dumps(payment_details)
        payment.updated_at = datetime.now(timezone.utc)
        
        if not challenge_id and payment_details.get('notes'):
            notes = payment_details.get('notes', {})
            challenge_id = notes.get('challenge_id')
        
        if payment.status == 'success' and challenge_id:
            challenge = ChallengeTemplate.query.get(challenge_id)
            if not challenge:
                flash('Challenge not found', 'error')
                return redirect(url_for('user.challenges'))
            
            payment.amount = challenge.price
            
            purchase = ChallengePurchase(
                user_id=user.id,
                challenge_template_id=challenge.id,
                purchase_date=datetime.now(timezone.utc),
                amount=challenge.price,
                payment_method='razorpay',
                status='active',
                start_date=datetime.now(timezone.utc),
                end_date=datetime.now(timezone.utc) + timedelta(days=challenge.duration_days),
                mt5_account=f"TRG_{user.id}_{challenge.id}_{datetime.now().strftime('%Y%m%d')}",
                current_profit=0.0,
                current_loss=0.0,
                phase=1,
                progress_percentage=0.0,
                days_remaining=challenge.duration_days
            )
            
            from utils.challenge_auth import get_next_serial_no, generate_challenge_code, generate_challenge_token
            purchase.serial_no = get_next_serial_no()
            purchase.challenge_code = generate_challenge_code()
            purchase.challenge_token = generate_challenge_token()
            
            db.session.add(purchase)
            db.session.flush()
            payment.challenge_purchase_id = purchase.id
            
            if DEV_MODE:
                print(f"🎯 Challenge purchase created: {purchase.id}")
            
            flash(f'✅ Payment successful! Your {challenge.name} account has been created.', 'success')
        else:
            flash('❌ Payment failed or invalid. Please try again.', 'error')
        
        db.session.commit()
        
        return redirect(url_for('user.payment_status', payment_id=payment.id))
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Payment verification error: {e}")
        flash('Error processing payment. Please contact support.', 'error')
        return redirect(url_for('user.challenges'))

@app.route('/payment/status/<int:payment_id>')
@login_required
def payment_status(payment_id):
    """Show payment status page"""
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
    """Show payment failed page"""
    return render_template('user/payment_failed.html', user=User.query.get(session['user_id']))

# ===== MAIN ROUTES =====
@app.route('/')
def home():
    return render_template('index.html', PRELAUNCH_MODE=PRELAUNCH_MODE)

@app.route('/legal')
def legal():
    return render_template('legal.html')

@app.route('/waitlist', methods=['GET'])
def waitlist():
    return render_template('waitlist/waitlist_form.html')

@app.route('/submit-waitlist', methods=['POST'])
def submit_waitlist():
    try:
        new_lead = WaitlistLead(
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            experience=request.form.get('experience'),
            platform=request.form.get('platform'),
            plan_interest=request.form.get('plan_interest'),
            problem=request.form.get('problem'),
            feedback=request.form.get('feedback'),
            early_access=request.form.get('early_access') == 'yes'
        )
        db.session.add(new_lead)
        db.session.commit()
        return redirect(url_for('waitlist_success'))
    except Exception as e:
        db.session.rollback()
        flash('Error joining waitlist. Please try again.', 'error')
        return redirect(url_for('waitlist'))

@app.route('/waitlist-success', methods=['GET'])
def waitlist_success():
    return render_template('waitlist/waitlist_success.html')

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
        print(f"Razorpay: {'ENABLED' if razorpay_client else 'DISABLED'}")
        
        important_templates = ['index.html', 'user/user_dashboard.html', 'login.html', 
                              'user/payment_status.html', 'user/payment_failed.html']
        for template in important_templates:
            template_path = os.path.join(app.template_folder, template)
            status = "OK" if os.path.exists(template_path) else "MISS"
            print(f"  [{status}] {template}")
    
    print("="*60 + "\n")
    
    app.run(debug=DEV_MODE, host='0.0.0.0', port=5003)