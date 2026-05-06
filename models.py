from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timezone, timedelta
from sqlalchemy import Index
import json

db = SQLAlchemy()

# ========================================================================
# ENUM CLASSES FOR TYPE SAFETY
# ========================================================================

class ChallengeStatus:
    PENDING_CREDENTIALS = 'pending_credentials'
    ACTIVE = 'active'
    PASSED = 'passed'
    FAILED = 'failed'
    EXPIRED = 'expired'
    REVOKED = 'revoked'
    
    ALL = [PENDING_CREDENTIALS, ACTIVE, PASSED, FAILED, EXPIRED, REVOKED]

class KYCStatus:
    PENDING = 'pending'
    SUBMITTED = 'submitted'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    
    ALL = [PENDING, SUBMITTED, APPROVED, REJECTED]

# ========================================================================
# MODELS WITH INDEXES AND FIXES
# ========================================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False, index=True)
    last_name = db.Column(db.String(50), nullable=False, index=True)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    dob = db.Column(db.Date, nullable=False)
    country = db.Column(db.String(50), nullable=False, index=True)
    state = db.Column(db.String(50))
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, index=True)
    is_banned = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    # KYC Fields
    phone_verified = db.Column(db.Boolean, default=False, index=True)
    email_verified = db.Column(db.Boolean, default=False, index=True)
    kyc_status = db.Column(db.String(20), default=KYCStatus.PENDING, index=True)
    id_front_url = db.Column(db.String(500), default='')
    id_back_url = db.Column(db.String(500), default='')
    document_type = db.Column(db.String(20), default='')
    document_number = db.Column(db.String(50), default='')
    kyc_submitted_at = db.Column(db.DateTime(timezone=True), default=None)
    kyc_notes = db.Column(db.Text, default='')
    
    # Email Verification Token
    email_verification_token = db.Column(db.String(100), index=True)
    
    # Phone OTP Fields
    phone_verification_code = db.Column(db.String(6))
    phone_verification_sent_at = db.Column(db.Float)  # Unix timestamp
    phone_verification_attempts = db.Column(db.Integer, default=0)
    
    # Security fields for balance manipulation detection
    last_balance_check = db.Column(db.DateTime(timezone=True), default=None)
    balance_check_hash = db.Column(db.String(64), default='')  # For detecting balance changes
    
    # Relationships
    challenge_purchases = db.relationship('ChallengePurchase', backref='user', lazy=True, cascade='all, delete-orphan')
    payouts = db.relationship('Payout', backref='user', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def get_age(self):
        today = date.today()
        return today.year - self.dob.year - ((today.month, today.day) < (self.dob.month, self.dob.day))
    
    def is_kyc_approved(self):
        return self.kyc_status == KYCStatus.APPROVED
    
    def can_buy_challenge(self):
        return self.is_kyc_approved() and not self.is_banned
    
    def is_kyc_submitted(self):
        return self.kyc_status == KYCStatus.SUBMITTED
    
    def is_kyc_pending(self):
        return self.kyc_status == KYCStatus.PENDING
    
    def get_kyc_status_display(self):
        status_map = {
            KYCStatus.PENDING: 'Not Started',
            KYCStatus.SUBMITTED: 'Under Review', 
            KYCStatus.APPROVED: 'Approved',
            KYCStatus.REJECTED: 'Rejected'
        }
        return status_map.get(self.kyc_status, 'Not Started')
    
    def auto_verify_email(self):
        """Auto verify email without sending actual email"""
        self.email_verified = True
        self.email_verification_token = None
        print(f"✅ Email auto-verified for: {self.email}")
        return True
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def __repr__(self):
        return f'<User {self.email}>'


class ChallengeTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    price = db.Column(db.Integer, nullable=False)
    account_size = db.Column(db.Integer, nullable=False)
    phase = db.Column(db.Integer, nullable=False)
    profit_target = db.Column(db.Float, nullable=False)
    max_daily_loss = db.Column(db.Float, nullable=False)
    max_overall_loss = db.Column(db.Float, nullable=False)
    min_trading_days = db.Column(db.Integer, nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)
    leverage = db.Column(db.String(20), default='1:100')
    user_profit_share = db.Column(db.Integer, nullable=False)
    payout_cycle = db.Column(db.String(20), default='biweekly')
    weekend_trading = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<ChallengeTemplate {self.name}>'


class ChallengePurchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    challenge_template_id = db.Column(db.Integer, db.ForeignKey('challenge_template.id'), nullable=False, index=True)
    
    # Purchase Details
    purchase_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    payment_method = db.Column(db.String(50))  # razorpay, dev-bypass, etc.
    
    # MT5 Credentials Fields
    mt5_server = db.Column(db.String(200), nullable=True)
    mt5_login = db.Column(db.String(100), nullable=True, index=True)
    mt5_password = db.Column(db.String(200), nullable=True)
    credentials_assigned_at = db.Column(db.DateTime(timezone=True), nullable=True)
    credentials_revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    # EA Monitoring Fields
    serial_no = db.Column(db.Integer, nullable=True, index=True)
    challenge_code = db.Column(db.String(6), nullable=True, index=True)
    challenge_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    ea_connected = db.Column(db.Boolean, default=False, index=True)
    ea_first_connection = db.Column(db.DateTime(timezone=True), nullable=True)
    last_heartbeat = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    
    # Trading Details
    start_date = db.Column(db.DateTime(timezone=True), index=True)
    end_date = db.Column(db.DateTime(timezone=True), index=True)
    current_profit = db.Column(db.Float, default=0.0)
    current_loss = db.Column(db.Float, default=0.0)
    max_drawdown_used = db.Column(db.Float, default=0.0)
    
    # Rule Tracking - ALL TIMES IN UTC
    starting_balance = db.Column(db.Float, default=0.0)
    starting_equity = db.Column(db.Float, default=0.0)
    current_balance = db.Column(db.Float, default=0.0)
    current_equity = db.Column(db.Float, default=0.0)
    peak_equity = db.Column(db.Float, default=0.0)  # For max DD calculation
    daily_start_equity = db.Column(db.Float, default=0.0)  # For daily DD
    daily_start_date = db.Column(db.Date, nullable=True, index=True)  # UTC date for day tracking
    
    # CRITICAL FIX: Tracker for balance manipulation detection
    last_verified_balance = db.Column(db.Float, default=0.0)
    last_verified_equity = db.Column(db.Float, default=0.0)
    last_balance_check_time = db.Column(db.DateTime(timezone=True), nullable=True)
    balance_check_hash = db.Column(db.String(64), default='')
    
    # Status
    status = db.Column(db.String(20), default=ChallengeStatus.PENDING_CREDENTIALS, index=True)
    phase = db.Column(db.Integer, default=1)
    
    # Violation Tracking
    violation_reason = db.Column(db.Text, nullable=True)
    violation_timestamp = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    pass_reason = db.Column(db.Text, nullable=True)
    
    # Progress Tracking
    progress_percentage = db.Column(db.Float, default=0.0)
    days_remaining = db.Column(db.Integer)
    trading_days_completed = db.Column(db.Integer, default=0, index=True)
    
    # Account Info (backward compatibility)
    mt5_account = db.Column(db.String(100))
    account_balance = db.Column(db.Float, default=0.0)
    equity = db.Column(db.Float, default=0.0)
    
    # Timestamps
    last_updated = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    
    # Relationships
    challenge_template = db.relationship('ChallengeTemplate', backref='purchases', lazy=True)
    payouts = db.relationship('Payout', backref='challenge_purchase', lazy=True, cascade='all, delete-orphan')
    payment = db.relationship('Payment', backref='challenge_purchase', uselist=False)
    
    # EA monitoring relationships
    account_snapshots = db.relationship('AccountSnapshot', backref='challenge', lazy=True, cascade='all, delete-orphan')
    ea_trades = db.relationship('EATrade', backref='challenge', lazy=True, cascade='all, delete-orphan')
    rule_violations = db.relationship('RuleViolation', backref='challenge', lazy=True, cascade='all, delete-orphan')
    
    # Simple methods only - business logic goes in engine
    def is_active(self):
        return self.status == ChallengeStatus.ACTIVE
    
    def has_credentials(self):
        return bool(self.mt5_login and self.mt5_password)
    
    def can_view_credentials(self):
        return self.is_active() and self.has_credentials()
    
    def get_days_remaining(self):
        """Simple calculation only"""
        if not self.end_date:
            return None
        remaining = (self.end_date - datetime.now(timezone.utc)).days
        return max(0, remaining)
    
    def assign_credentials(self, server, login, password, challenge_token=None):
        """Assign MT5 credentials"""
        self.mt5_server = server
        self.mt5_login = login
        self.mt5_password = password
        self.credentials_assigned_at = datetime.now(timezone.utc)
        self.status = ChallengeStatus.ACTIVE
        
        # Generate challenge token if not provided
        if challenge_token:
            self.challenge_token = challenge_token
        else:
            import secrets
            self.challenge_token = secrets.token_urlsafe(16)
        
        # Set start and end dates
        if not self.start_date:
            self.start_date = datetime.now(timezone.utc)
        if not self.end_date and self.challenge_template:
            self.end_date = datetime.now(timezone.utc) + timedelta(days=self.challenge_template.duration_days)
    
    def revoke_credentials(self):
        """Revoke MT5 access"""
        self.mt5_server = None
        self.mt5_login = None
        self.mt5_password = None
        self.credentials_revoked_at = datetime.now(timezone.utc)
        self.status = ChallengeStatus.REVOKED
    
    def is_heartbeat_alive(self, timeout_seconds=600):
        """Check if EA is still sending data"""
        if not self.last_heartbeat:
            return False
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
        return elapsed < timeout_seconds
    
    def get_current_state(self):
        """Return current state dict for engine"""
        return {
            'equity': self.current_equity,
            'balance': self.current_balance,
            'starting_equity': self.starting_equity,
            'peak_equity': self.peak_equity,
            'daily_start_equity': self.daily_start_equity,
            'daily_start_date': self.daily_start_date,
            'max_drawdown_used': self.max_drawdown_used,
            'current_profit': self.current_profit,
            'trading_days_completed': self.trading_days_completed,
            'status': self.status
        }
    
    def __repr__(self):
        return f'<ChallengePurchase {self.id} - User {self.user_id}>'


class AccountSnapshot(db.Model):
    """Store every heartbeat from EA"""
    __tablename__ = 'account_snapshot'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    
    # Snapshot Metadata
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    ea_version = db.Column(db.String(20))
    terminal_build = db.Column(db.Integer)
    
    # Account Info
    mt5_login = db.Column(db.String(100), index=True)
    broker_server = db.Column(db.String(200))
    
    # Financial Data
    balance = db.Column(db.Float, nullable=False)
    equity = db.Column(db.Float, nullable=False)
    free_margin = db.Column(db.Float, default=0.0)
    margin_used = db.Column(db.Float, default=0.0)
    credit = db.Column(db.Float, default=0.0)  # For bonus abuse detection
    leverage = db.Column(db.Integer)
    currency = db.Column(db.String(10), default='USD')
    
    # Calculated values
    profit_from_start = db.Column(db.Float, default=0.0, index=True)
    drawdown_from_peak = db.Column(db.Float, default=0.0, index=True)
    
    # Open positions
    open_positions_count = db.Column(db.Integer, default=0)
    
    # Retention management
    is_archived = db.Column(db.Boolean, default=False, index=True)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f'<Snapshot {self.id} - Challenge {self.challenge_purchase_id} - {self.timestamp}>'
    
    __table_args__ = (
        Index('idx_snapshot_challenge_timestamp', 'challenge_purchase_id', 'timestamp'),
        Index('idx_snapshot_challenge_archived', 'challenge_purchase_id', 'is_archived'),
    )


class EATrade(db.Model):
    """Store trades from EA"""
    __tablename__ = 'ea_trade'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    
    # Trade Identifiers
    ticket = db.Column(db.BigInteger, nullable=False, index=True)
    symbol = db.Column(db.String(20), nullable=False, index=True)
    trade_type = db.Column(db.Integer, nullable=False)  # 0=BUY, 1=SELL
    
    # Trade Details
    lots = db.Column(db.Float, nullable=False)
    open_price = db.Column(db.Float, default=0.0)
    close_price = db.Column(db.Float, default=0.0)
    current_price = db.Column(db.Float, default=0.0)
    
    # Profit/Loss
    profit = db.Column(db.Float, default=0.0)
    floating_pnl = db.Column(db.Float, default=0.0)
    
    # Stop Loss / Take Profit
    sl = db.Column(db.Float, default=0.0)
    tp = db.Column(db.Float, default=0.0)
    
    # Magic Number
    magic = db.Column(db.BigInteger, default=0, index=True)
    
    # Timestamps
    open_time = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    close_time = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    
    # Status
    status = db.Column(db.String(20), default='open', index=True)
    
    # Metadata
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Retention
    is_archived = db.Column(db.Boolean, default=False, index=True)
    
    # Constraints
    __table_args__ = (
        db.UniqueConstraint('challenge_purchase_id', 'ticket', name='unique_challenge_ticket'),
        Index('idx_trade_challenge_status', 'challenge_purchase_id', 'status'),
        Index('idx_trade_challenge_close', 'challenge_purchase_id', 'close_time'),
        Index('idx_trade_magic', 'magic', 'challenge_purchase_id'),
    )
    
    def is_manual_trade(self):
        return self.magic == 0
    
    def is_bot_trade(self):
        return self.magic > 0
    
    def __repr__(self):
        return f'<EATrade {self.ticket} - {self.symbol} - {self.status}>'


class RuleViolation(db.Model):
    """Log every rule violation"""
    __tablename__ = 'rule_violation'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    
    # Violation Details
    rule_name = db.Column(db.String(100), nullable=False, index=True)
    rule_value_limit = db.Column(db.Float)
    rule_value_actual = db.Column(db.Float)
    
    # Context
    violation_message = db.Column(db.Text, nullable=False)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('account_snapshot.id'), nullable=True)
    
    # Severity
    severity = db.Column(db.String(20), default='hard_fail', index=True)  # hard_fail, warning, info
    is_hard_fail = db.Column(db.Boolean, default=True, index=True)
    
    # Action taken
    action_taken = db.Column(db.String(50), default='logged')  # logged, failed_challenge, warned, etc.
    
    # Timestamps
    violated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    # Relationship
    snapshot = db.relationship('AccountSnapshot', backref='violations', lazy=True)
    
    def __repr__(self):
        return f'<RuleViolation {self.rule_name} - Challenge {self.challenge_purchase_id}>'
    
    __table_args__ = (
        Index('idx_violation_challenge_rule', 'challenge_purchase_id', 'rule_name'),
        Index('idx_violation_severity_date', 'severity', 'violated_at'),
    )


class DailySnapshot(db.Model):
    """Store end-of-day summaries"""
    __tablename__ = 'daily_snapshot'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    
    # Date (UTC)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)
    
    # Day Start/End
    start_equity = db.Column(db.Float, nullable=False)
    end_equity = db.Column(db.Float, nullable=False)
    start_balance = db.Column(db.Float, nullable=False)
    end_balance = db.Column(db.Float, nullable=False)
    
    # Day Stats
    lowest_equity = db.Column(db.Float)
    highest_equity = db.Column(db.Float)
    
    # Trading Activity
    trades_opened = db.Column(db.Integer, default=0)
    trades_closed = db.Column(db.Integer, default=0)
    closed_profit = db.Column(db.Float, default=0.0)
    closed_loss = db.Column(db.Float, default=0.0)
    net_pnl = db.Column(db.Float, default=0.0)
    
    # Flags
    is_trading_day = db.Column(db.Boolean, default=False, index=True)
    violated_daily_dd = db.Column(db.Boolean, default=False, index=True)
    had_manual_trades = db.Column(db.Boolean, default=False, index=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # Constraints
    __table_args__ = (
        db.UniqueConstraint('challenge_purchase_id', 'snapshot_date', name='unique_challenge_date'),
        Index('idx_daily_challenge_date', 'challenge_purchase_id', 'snapshot_date', 'is_trading_day'),
        Index('idx_daily_trading_status', 'challenge_purchase_id', 'is_trading_day', 'snapshot_date'),
    )
    
    def __repr__(self):
        return f'<DailySnapshot {self.snapshot_date} - Challenge {self.challenge_purchase_id}>'


# ========================================================================
# EXISTING MODELS (OPTIMIZED)
# ========================================================================

class Payout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    
    # Payout Details
    amount = db.Column(db.Float, nullable=False)
    profit_share_percentage = db.Column(db.Float, nullable=False)
    
    # Status
    status = db.Column(db.String(20), default='pending', index=True)
    admin_notes = db.Column(db.Text, default='')
    
    # Payment Info
    payout_date = db.Column(db.DateTime(timezone=True), index=True)
    due_date = db.Column(db.DateTime(timezone=True), index=True)
    payment_method = db.Column(db.String(50))
    transaction_id = db.Column(db.String(100))
    bank_account_details = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<Payout {self.id} - ${self.amount}>'


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=True, index=True)
    
    # Payment Details
    payment_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='INR')
    payment_method = db.Column(db.String(20), nullable=False)
    gateway = db.Column(db.String(50), default='razorpay')
    
    # Status
    status = db.Column(db.String(20), default='pending', index=True)
    
    # Gateway Info
    gateway_id = db.Column(db.String(100))
    gateway_order_id = db.Column(db.String(100))
    gateway_response = db.Column(db.Text)
    
    # Metadata
    notes = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<Payment {self.payment_id} - {self.status}>'


class AdminLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    target_type = db.Column(db.String(50), index=True)
    target_id = db.Column(db.Integer, index=True)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    admin = db.relationship('User', backref='admin_logs', lazy=True)
    
    def __repr__(self):
        return f'<AdminLog {self.action} by {self.admin_id}>'


class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='open', index=True)
    priority = db.Column(db.String(20), default='normal', index=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    resolution = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    
    user = db.relationship('User', foreign_keys=[user_id], backref='support_tickets', lazy=True)
    assignee = db.relationship('User', foreign_keys=[assigned_to], lazy=True)
    
    def __repr__(self):
        return f'<SupportTicket {self.id} - {self.subject}>'


class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    
    # Trade Details
    trade_id = db.Column(db.String(100), unique=True, index=True)
    symbol = db.Column(db.String(20), nullable=False, index=True)
    trade_type = db.Column(db.String(10), nullable=False)
    volume = db.Column(db.Float, nullable=False)
    open_price = db.Column(db.Float, nullable=False)
    close_price = db.Column(db.Float)
    open_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    close_time = db.Column(db.DateTime(timezone=True), index=True)
    swap = db.Column(db.Float, default=0.0)
    commission = db.Column(db.Float, default=0.0)
    
    # Profit/Loss
    profit = db.Column(db.Float, default=0.0)
    
    # Status
    status = db.Column(db.String(20), default='open', index=True)
    
    # Metadata
    notes = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    challenge_purchase = db.relationship('ChallengePurchase', backref='trades', lazy=True)
    
    def __repr__(self):
        return f'<Trade {self.trade_id} - {self.symbol}>'


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Notification Details
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), index=True)
    
    # Status
    is_read = db.Column(db.Boolean, default=False, index=True)
    
    # Metadata
    action_url = db.Column(db.String(500))
    icon = db.Column(db.String(50))
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    user = db.relationship('User', backref='notifications', lazy=True)
    
    def __repr__(self):
        return f'<Notification {self.id} - {self.title}>'


class WaitlistLead(db.Model):
    __tablename__ = 'waitlist_leads'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=False)
    experience = db.Column(db.String(50))
    platform = db.Column(db.String(50))
    plan_interest = db.Column(db.String(100))
    problem = db.Column(db.Text)
    feedback = db.Column(db.Text)
    early_access = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='new', index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<WaitlistLead {self.email}>'