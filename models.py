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

class MonitoringStatus:
    ACTIVE = 'active'
    OFFLINE = 'offline'
    UNDER_REVIEW = 'under_review'
    FLAGGED = 'flagged'
    
    ALL = [ACTIVE, OFFLINE, UNDER_REVIEW, FLAGGED]

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
    role = db.Column(db.String(20), default='user')
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
    
    # Password Reset Tokens
    reset_token = db.Column(db.String(255), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    
    # Phone OTP Fields
    phone_verification_code = db.Column(db.String(6))
    phone_verification_sent_at = db.Column(db.Float)
    phone_verification_attempts = db.Column(db.Integer, default=0)
    
    # Security fields for balance manipulation detection
    last_balance_check = db.Column(db.DateTime(timezone=True), default=None)
    balance_check_hash = db.Column(db.String(64), default='')
    
    # Personalization & Levels
    trading_alias = db.Column(db.String(50), default='')
    trader_level = db.Column(db.String(50), default='Starter')
    is_compact_view = db.Column(db.Boolean, default=False)

    # Relationships - FIXED: using string reference with proper backref names
    challenge_purchases = db.relationship('TradingJourney', backref='user_obj', lazy=True, cascade='all, delete-orphan')
    payouts = db.relationship('Payout', backref='user_obj', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='user_obj', lazy=True, cascade='all, delete-orphan', foreign_keys='Payment.user_id')
    
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
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def __repr__(self):
        return f'<User {self.email}>'


class PartnerEarnings(db.Model):
    __tablename__ = 'partner_earnings'
    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenge_template.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    purchase_amount = db.Column(db.Float, nullable=False)
    partner_share = db.Column(db.Float, nullable=False)
    purchased_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_hidden = db.Column(db.Boolean, default=False)

    partner = db.relationship('User', foreign_keys=[partner_id], backref='partner_earnings_list')
    user = db.relationship('User', foreign_keys=[user_id])
    challenge = db.relationship('ChallengeTemplate')


class ChallengeTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    price = db.Column(db.Integer, nullable=False)
    account_size = db.Column(db.Integer, nullable=False)
    phase = db.Column(db.Integer, nullable=False, default=1)

    # Phase 1 Rules
    phase1_target = db.Column(db.Float, nullable=True)
    phase1_daily_loss = db.Column(db.Float, nullable=True)
    phase1_overall_loss = db.Column(db.Float, nullable=True)
    phase1_min_days = db.Column(db.Integer, nullable=True)
    phase1_duration = db.Column(db.Integer, nullable=True)
    phase1_leverage = db.Column(db.String(20), nullable=True)
    phase1_rules = db.Column(db.Text, nullable=True)

    # Phase 2 Rules
    phase2_target = db.Column(db.Float, nullable=True)
    phase2_daily_loss = db.Column(db.Float, nullable=True)
    phase2_overall_loss = db.Column(db.Float, nullable=True)
    phase2_min_days = db.Column(db.Integer, nullable=True)
    phase2_duration = db.Column(db.Integer, nullable=True)
    phase2_leverage = db.Column(db.String(20), nullable=True)
    phase2_rules = db.Column(db.Text, nullable=True)

    # Instant Rules
    instant_daily_loss = db.Column(db.Float, nullable=True)
    instant_overall_loss = db.Column(db.Float, nullable=True)
    instant_min_days = db.Column(db.Integer, nullable=True)
    instant_leverage = db.Column(db.String(20), nullable=True)
    instant_rules = db.Column(db.Text, nullable=True)

    user_profit_share = db.Column(db.Integer, nullable=False)
    payout_cycle = db.Column(db.String(20), default='biweekly')
    weekend_trading = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    description = db.Column(db.Text)
    challenge_type = db.Column(db.String(20), nullable=False, default='one_phase', index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships - FIXED: using string reference
    purchases = db.relationship('TradingJourney', backref='challenge_template', lazy=True)
    
    @property
    def profit_target(self):
        if self.challenge_type == 'instant':
            return 0.0
        return self.phase1_target or 0.0

    @property
    def max_daily_loss(self):
        if self.challenge_type == 'instant':
            return self.instant_daily_loss or 0.0
        return self.phase1_daily_loss or 0.0

    @property
    def max_overall_loss(self):
        if self.challenge_type == 'instant':
            return self.instant_overall_loss or 0.0
        return self.phase1_overall_loss or 0.0

    @property
    def min_trading_days(self):
        if self.challenge_type == 'instant':
            return self.instant_min_days or 0
        return self.phase1_min_days or 0

    @property
    def duration_days(self):
        if self.challenge_type == 'instant':
            return 365
        return self.phase1_duration or 30

    @property
    def leverage(self):
        if self.challenge_type == 'instant':
            return self.instant_leverage or "1:100"
        return self.phase1_leverage or "1:100"

    def __repr__(self):
        return f'<ChallengeTemplate {self.name}>'


class TradingJourney(db.Model):
    __tablename__ = 'challenge_purchase'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    challenge_template_id = db.Column(db.Integer, db.ForeignKey('challenge_template.id'), nullable=False, index=True)
    
    # Purchase Details
    purchase_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    payment_method = db.Column(db.String(50))
    
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
    peak_equity = db.Column(db.Float, default=0.0)
    daily_start_equity = db.Column(db.Float, default=0.0)
    daily_start_date = db.Column(db.Date, nullable=True, index=True)
    
    # Additional metrics for rule engine
    highest_equity = db.Column(db.Float, default=0.0)
    daily_drawdown = db.Column(db.Float, default=0.0)
    overall_drawdown = db.Column(db.Float, default=0.0)
    profit_percent = db.Column(db.Float, default=0.0)
    trading_days = db.Column(db.Integer, default=0)
    lowest_equity_today = db.Column(db.Float, nullable=True)
    highest_equity_today = db.Column(db.Float, nullable=True)
    day_start_equity = db.Column(db.Float, nullable=True)
    
    # Risk and monitoring
    risk_score = db.Column(db.Integer, default=0)
    monitoring_status = db.Column(db.String(30), default=MonitoringStatus.ACTIVE)
    review_required = db.Column(db.Boolean, default=False)
    
    # Phase progression tracking
    phase1_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    phase2_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    funded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    # Phase tracking (preserves lifetime stats)
    phase_start_balance = db.Column(db.Float, default=0.0)
    phase_start_equity = db.Column(db.Float, default=0.0)
    phase_start_date = db.Column(db.DateTime(timezone=True), nullable=True)
    phase_trading_days = db.Column(db.Integer, default=0)
    phase_profit_percent = db.Column(db.Float, default=0.0)

    # Phase daily tracking
    phase_daily_drawdown = db.Column(db.Float, default=0.0)
    phase_day_start_equity = db.Column(db.Float, default=0.0)
    phase_lowest_equity_today = db.Column(db.Float, default=0.0)
    phase_daily_start_date = db.Column(db.Date, nullable=True)

    # Distance metrics
    distance_to_payout = db.Column(db.Float, nullable=True)
    distance_to_breach = db.Column(db.Float, nullable=True)

    # Last trade date
    last_trade_date = db.Column(db.Date, nullable=True)
    
    # Tracker for balance manipulation detection
    last_verified_balance = db.Column(db.Float, default=0.0)
    last_verified_equity = db.Column(db.Float, default=0.0)
    last_balance_check_time = db.Column(db.DateTime(timezone=True), nullable=True)
    balance_check_hash = db.Column(db.String(64), default='')
    
    # NEW: Fresh start baseline for manipulation checks
    manipulation_check_baseline = db.Column(db.Float, nullable=True)
    manipulation_baseline_set_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    # Persistent State Fields
    challenge_type = db.Column(db.String(20), nullable=False, default='one_phase', index=True)
    current_phase = db.Column(db.Integer, nullable=False, default=1)
    is_terminated = db.Column(db.Boolean, nullable=False, default=False, index=True)
    
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
    
    # FIXED: Added created_at for backward compatibility
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    # Relationships - FIXED: using string references to avoid circular imports
    payouts = db.relationship('Payout', backref='challenge_purchase_obj', lazy=True, cascade='all, delete-orphan')
    payment = db.relationship('Payment', backref='challenge_purchase_obj', uselist=False)
    
    # EA monitoring relationships
    account_snapshots = db.relationship('AccountSnapshot', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    ea_trades = db.relationship('EATrade', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    rule_violations = db.relationship('RuleViolation', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    
    # Rule engine relationships
    rule_logs = db.relationship('RuleLog', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    trade_history = db.relationship('TradeHistory', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    trades = db.relationship('Trade', backref='challenge_purchase_obj', lazy=True)
    coupon_usage = db.relationship('CouponUsage', backref='challenge_purchase_obj', uselist=False)
    
    # Simple methods only - business logic goes in engine
    def is_active(self):
        return self.status == ChallengeStatus.ACTIVE
    
    def has_credentials(self):
        return bool(self.mt5_login and self.mt5_password)
    
    def can_view_credentials(self):
        return self.is_active() and self.has_credentials()
    
    def get_days_remaining(self):
        if not self.end_date:
            return None
        remaining = (self.end_date - datetime.now(timezone.utc)).days
        return max(0, remaining)
    
    def assign_credentials(self, server, login, password, challenge_token=None):
        self.mt5_server = server
        self.mt5_login = login
        self.mt5_password = password
        self.credentials_assigned_at = datetime.now(timezone.utc)
        self.status = ChallengeStatus.ACTIVE
        self.monitoring_status = MonitoringStatus.ACTIVE
        
        if self.phase_start_balance == 0:
            self.phase_start_balance = float(self.current_balance) if self.current_balance else float(self.starting_balance)
            self.phase_start_equity = float(self.current_equity) if self.current_equity else float(self.starting_equity)
            self.phase_start_date = datetime.now(timezone.utc)
            self.phase_trading_days = 0
            self.phase_profit_percent = 0.0
            self.phase_daily_drawdown = 0.0
            self.phase_day_start_equity = float(self.current_equity) if self.current_equity else float(self.starting_equity)
            self.phase_lowest_equity_today = float(self.current_equity) if self.current_equity else float(self.starting_equity)
            self.phase_daily_start_date = datetime.now(timezone.utc).date()
        
        if challenge_token:
            self.challenge_token = challenge_token
        else:
            import secrets
            self.challenge_token = secrets.token_urlsafe(16)
        
        if not self.start_date:
            self.start_date = datetime.now(timezone.utc)
        if not self.end_date and self.challenge_template:
            self.end_date = datetime.now(timezone.utc) + timedelta(days=self.challenge_template.duration_days)
    
    def revoke_credentials(self):
        self.mt5_server = None
        self.mt5_login = None
        self.mt5_password = None
        self.credentials_revoked_at = datetime.now(timezone.utc)
        self.status = ChallengeStatus.REVOKED
    
    def is_heartbeat_alive(self, timeout_seconds=600):
        if not self.last_heartbeat:
            return False
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
        return elapsed < timeout_seconds
    
    def get_current_state(self):
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
            'status': self.status,
            'profit_percent': self.profit_percent,
            'daily_drawdown': self.daily_drawdown,
            'overall_drawdown': self.overall_drawdown,
            'risk_score': self.risk_score,
            'monitoring_status': self.monitoring_status,
            'phase_profit_percent': self.phase_profit_percent,
            'phase_trading_days': self.phase_trading_days,
            'distance_to_payout': self.distance_to_payout,
            'distance_to_breach': self.distance_to_breach
        }
    
    def __repr__(self):
        return f'<ChallengePurchase {self.id} - User {self.user_id}>'

# Alias for backward compatibility
ChallengePurchase = TradingJourney


# ========================================================================
# NEW MODELS FOR RULE ENGINE
# ========================================================================

class RuleLog(db.Model):
    __tablename__ = 'rule_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    rule_name = db.Column(db.String(100), nullable=False, index=True)
    severity = db.Column(db.String(20), default='info', index=True)
    message = db.Column(db.Text, nullable=False)
    current_value = db.Column(db.Float, nullable=True)
    threshold_value = db.Column(db.Float, nullable=True)
    additional_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    __table_args__ = (
        Index('idx_rulelog_challenge_rule', 'challenge_id', 'rule_name'),
        Index('idx_rulelog_severity_date', 'severity', 'created_at'),
    )
    
    def __repr__(self):
        return f'<RuleLog {self.rule_name} - {self.severity}>'


class TradeHistory(db.Model):
    __tablename__ = 'trade_history'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    ticket = db.Column(db.BigInteger, nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    lots = db.Column(db.Float, nullable=False)
    open_price = db.Column(db.Float, nullable=False)
    close_price = db.Column(db.Float, nullable=True)
    profit = db.Column(db.Float, default=0.0)
    swap = db.Column(db.Float, default=0.0)
    commission = db.Column(db.Float, default=0.0)
    sl = db.Column(db.Float, default=0.0)
    tp = db.Column(db.Float, default=0.0)
    open_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    close_time = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    is_open = db.Column(db.Boolean, default=True, index=True)
    magic_number = db.Column(db.BigInteger, default=0)
    comment = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        db.UniqueConstraint('challenge_id', 'ticket', name='unique_challenge_ticket_history'),
        Index('idx_tradehistory_challenge_open', 'challenge_id', 'is_open'),
        Index('idx_tradehistory_close_date', 'close_time'),
    )
    
    def __repr__(self):
        return f'<TradeHistory {self.ticket} - {self.symbol}>'


# ========================================================================
# EXISTING MODELS (unchanged below)
# ========================================================================

class AccountSnapshot(db.Model):
    __tablename__ = 'account_snapshot'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    ea_version = db.Column(db.String(20))
    terminal_build = db.Column(db.Integer)
    mt5_login = db.Column(db.String(100), index=True)
    broker_server = db.Column(db.String(200))
    balance = db.Column(db.Float, nullable=False)
    equity = db.Column(db.Float, nullable=False)
    free_margin = db.Column(db.Float, default=0.0)
    margin_used = db.Column(db.Float, default=0.0)
    credit = db.Column(db.Float, default=0.0)
    leverage = db.Column(db.Integer)
    currency = db.Column(db.String(10), default='USD')
    profit_from_start = db.Column(db.Float, default=0.0, index=True)
    drawdown_from_peak = db.Column(db.Float, default=0.0, index=True)
    open_positions_count = db.Column(db.Integer, default=0)
    is_archived = db.Column(db.Boolean, default=False, index=True)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f'<Snapshot {self.id} - Challenge {self.challenge_purchase_id} - {self.timestamp}>'
    
    __table_args__ = (
        Index('idx_snapshot_challenge_timestamp', 'challenge_purchase_id', 'timestamp'),
        Index('idx_snapshot_challenge_archived', 'challenge_purchase_id', 'is_archived'),
    )


class EATrade(db.Model):
    __tablename__ = 'ea_trade'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    ticket = db.Column(db.BigInteger, nullable=False, index=True)
    symbol = db.Column(db.String(20), nullable=False, index=True)
    trade_type = db.Column(db.Integer, nullable=False)
    lots = db.Column(db.Float, nullable=False)
    open_price = db.Column(db.Float, default=0.0)
    close_price = db.Column(db.Float, default=0.0)
    current_price = db.Column(db.Float, default=0.0)
    profit = db.Column(db.Float, default=0.0)
    floating_pnl = db.Column(db.Float, default=0.0)
    sl = db.Column(db.Float, default=0.0)
    tp = db.Column(db.Float, default=0.0)
    magic = db.Column(db.BigInteger, default=0, index=True)
    open_time = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    close_time = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    status = db.Column(db.String(20), default='open', index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_archived = db.Column(db.Boolean, default=False, index=True)
    
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
    __tablename__ = 'rule_violation'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    rule_name = db.Column(db.String(100), nullable=False, index=True)
    rule_value_limit = db.Column(db.Float)
    rule_value_actual = db.Column(db.Float)
    violation_message = db.Column(db.Text, nullable=False)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('account_snapshot.id'), nullable=True)
    severity = db.Column(db.String(20), default='hard_fail', index=True)
    is_hard_fail = db.Column(db.Boolean, default=True, index=True)
    action_taken = db.Column(db.String(50), default='logged')
    violated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    snapshot = db.relationship('AccountSnapshot', backref='violations', lazy=True)
    
    def __repr__(self):
        return f'<RuleViolation {self.rule_name} - Challenge {self.challenge_purchase_id}>'
    
    __table_args__ = (
        Index('idx_violation_challenge_rule', 'challenge_purchase_id', 'rule_name'),
        Index('idx_violation_severity_date', 'severity', 'violated_at'),
    )


class DailySnapshot(db.Model):
    __tablename__ = 'daily_snapshot'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)
    start_equity = db.Column(db.Float, nullable=False)
    end_equity = db.Column(db.Float, nullable=False)
    start_balance = db.Column(db.Float, nullable=False)
    end_balance = db.Column(db.Float, nullable=False)
    lowest_equity = db.Column(db.Float)
    highest_equity = db.Column(db.Float)
    trades_opened = db.Column(db.Integer, default=0)
    trades_closed = db.Column(db.Integer, default=0)
    closed_profit = db.Column(db.Float, default=0.0)
    closed_loss = db.Column(db.Float, default=0.0)
    net_pnl = db.Column(db.Float, default=0.0)
    is_trading_day = db.Column(db.Boolean, default=False, index=True)
    violated_daily_dd = db.Column(db.Boolean, default=False, index=True)
    had_manual_trades = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        db.UniqueConstraint('challenge_purchase_id', 'snapshot_date', name='unique_challenge_date'),
        Index('idx_daily_challenge_date', 'challenge_purchase_id', 'snapshot_date', 'is_trading_day'),
        Index('idx_daily_trading_status', 'challenge_purchase_id', 'is_trading_day', 'snapshot_date'),
    )
    
    def __repr__(self):
        return f'<DailySnapshot {self.snapshot_date} - Challenge {self.challenge_purchase_id}>'


class Payout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    profit_share_percentage = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending', index=True)
    username_snapshot = db.Column(db.String(120), default='')
    challenge_name_snapshot = db.Column(db.String(150), default='')
    account_type_snapshot = db.Column(db.String(50), default='')
    account_size_snapshot = db.Column(db.Float, default=0.0)
    available_profit_snapshot = db.Column(db.Float, default=0.0)
    admin_notes = db.Column(db.Text, default='')
    rejection_reason = db.Column(db.Text, default='')
    expected_payment_time = db.Column(db.String(100), default='')
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    payout_date = db.Column(db.DateTime(timezone=True), index=True)
    due_date = db.Column(db.DateTime(timezone=True), index=True)
    payment_method = db.Column(db.String(50))
    account_holder_name = db.Column(db.String(120), default='')
    upi_id = db.Column(db.String(120), default='')
    transaction_id = db.Column(db.String(100))
    bank_account_details = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # FIXED: Use string references for relationships
    user = db.relationship('User', backref='payouts_list', foreign_keys=[user_id])
    challenge_purchase = db.relationship('TradingJourney', backref='payouts_list', foreign_keys=[challenge_purchase_id])
    
    def __repr__(self):
        return f'<Payout {self.id} - ${self.amount}>'


class PayoutAuditLog(db.Model):
    __tablename__ = 'payout_audit_log'
    id = db.Column(db.Integer, primary_key=True)
    payout_id = db.Column(db.Integer, db.ForeignKey('payout.id'), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    admin_username = db.Column(db.String(120), default='')
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    payout = db.relationship('Payout', backref=db.backref('audit_logs', cascade='all, delete-orphan', lazy=True))
    admin = db.relationship('User', foreign_keys=[admin_user_id])

    def __repr__(self):
        return f'<PayoutAuditLog {self.action} - Payout {self.payout_id}>'


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=True, index=True)
    payment_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    expected_amount = db.Column(db.Float, nullable=False, default=0.0)
    paid_amount = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default='INR')
    payment_method = db.Column(db.String(50), nullable=False)
    gateway = db.Column(db.String(50), default='cashfree')
    challenge_template_id = db.Column(db.Integer, nullable=True, index=True)
    cf_order_id = db.Column(db.String(100), index=True)
    cf_payment_id = db.Column(db.String(100))
    payment_session_id = db.Column(db.String(200))
    status = db.Column(db.String(20), default='pending', index=True)
    gateway_id = db.Column(db.String(100))
    gateway_order_id = db.Column(db.String(100))
    gateway_response = db.Column(db.Text)
    gateway_status = db.Column(db.String(50))
    gateway_message = db.Column(db.Text)
    refund_status = db.Column(db.String(20), default='none', index=True)
    refund_eligible = db.Column(db.Boolean, default=False)
    refund_verified_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    refund_requested_at = db.Column(db.DateTime(timezone=True), nullable=True)
    refund_processed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    notes = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.Text)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # FIXED: Use string references for relationships
    user = db.relationship('User', backref='payments_list', foreign_keys=[user_id])
    challenge_purchase = db.relationship('TradingJourney', backref='payment_obj', foreign_keys=[challenge_purchase_id])
    coupon = db.relationship('Coupon', backref='payments_list')

    def __repr__(self):
        return f'<Payment {self.payment_id} - {self.status}>'


class WebhookLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(100), index=True)
    order_id = db.Column(db.String(100), index=True)
    raw_payload = db.Column(db.Text, nullable=False)
    headers = db.Column(db.Text)
    signature = db.Column(db.String(500))
    status = db.Column(db.String(50), default='pending', index=True)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    processed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f'<WebhookLog {self.event_type} - {self.order_id} - {self.status}>'


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


class AdminAuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=True, index=True)
    old_value = db.Column(db.String(255))
    new_value = db.Column(db.String(255))
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    admin = db.relationship('User', foreign_keys=[admin_id], backref='audit_logs', lazy=True)
    payment = db.relationship('Payment', backref='audit_logs', lazy=True)
    
    def __repr__(self):
        return f'<AdminAuditLog {self.action} by {self.admin_id}>'


class SupportTicket(db.Model):
    __tablename__ = 'support_ticket'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    subject = db.Column(db.String(200), nullable=False)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False)
    category = db.Column(db.String(100), default='General', index=True)
    status = db.Column(db.String(20), default='open', index=True)
    priority = db.Column(db.String(20), default='normal', index=True)
    admin_note = db.Column(db.Text, default='')
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    is_deleted = db.Column(db.Boolean, default=False, index=True)
    last_reply_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_user_read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_admin_read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    user = db.relationship('User', foreign_keys=[user_id], backref='support_tickets', lazy=True)
    assignee = db.relationship('User', foreign_keys=[assigned_to], lazy=True)
    messages = db.relationship('TicketMessage', backref='ticket', cascade='all, delete-orphan', lazy='dynamic')
    
    def __repr__(self):
        return f'<SupportTicket {self.ticket_number} - {self.subject}>'


class TicketMessage(db.Model):
    __tablename__ = 'ticket_message'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('support_ticket.id'), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_admin_reply = db.Column(db.Boolean, default=False)
    attachment_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sender = db.relationship('User', foreign_keys=[sender_id], lazy=True)

    def __repr__(self):
        return f'<TicketMessage {self.id} for Ticket {self.ticket_id}>'


class FAQ(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), index=True)
    is_pinned = db.Column(db.Boolean, default=False, index=True)
    helpful_yes = db.Column(db.Integer, default=0)
    helpful_no = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<FAQ {self.question[:30]}>'


class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
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
    profit = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='open', index=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    challenge_purchase = db.relationship('TradingJourney', backref='trade_list', lazy=True)
    
    def __repr__(self):
        return f'<Trade {self.trade_id} - {self.symbol}>'


class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    is_global = db.Column(db.Boolean, default=True, index=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, index=True)

    target_user = db.relationship('User', foreign_keys=[target_user_id], backref='targeted_notifications', lazy=True)
    admin = db.relationship('User', foreign_keys=[created_by_admin_id], backref='created_notifications', lazy=True)
    
    def __repr__(self):
        return f'<Notification {self.id} - {self.title}>'


class NotificationTemplate(db.Model):
    __tablename__ = 'notification_template'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default='general', index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    use_count = db.Column(db.Integer, default=0)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    created_by = db.relationship('User', foreign_keys=[created_by_admin_id], backref='created_templates', lazy=True)
    
    def increment_use_count(self):
        self.use_count += 1
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'title': self.title,
            'message': self.message,
            'category': self.category,
            'is_active': self.is_active,
            'use_count': self.use_count,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None
        }
    
    def __repr__(self):
        return f'<NotificationTemplate {self.name} - {self.category}>'


class UserNotification(db.Model):
    __tablename__ = 'user_notification'
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notification.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)

    notification = db.relationship('Notification', backref=db.backref('user_statuses', cascade='all, delete-orphan', lazy=True))
    user = db.relationship('User', backref=db.backref('read_statuses', cascade='all, delete-orphan', lazy=True))
    
    def __repr__(self):
        return f'<UserNotification {self.id} - User {self.user_id} - Read: {self.is_read}>'


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


class BlogPost(db.Model):
    __tablename__ = 'blog_posts'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    meta_description = db.Column(db.String(255), nullable=False)
    date_published = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    def __repr__(self):
        return f'<BlogPost {self.title}>'


class Coupon(db.Model):
    __tablename__ = 'coupon'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    coupon_type = db.Column(db.String(20), nullable=False, default='universal')
    discount_type = db.Column(db.String(20), nullable=False, default='percent')
    discount_value = db.Column(db.Float, nullable=False)
    max_uses = db.Column(db.Integer, nullable=True)
    used_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    influencer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    influencer = db.relationship('User', foreign_keys=[influencer_id], backref='influencer_coupons')
    admin = db.relationship('User', foreign_keys=[created_by_admin_id])

    @property
    def is_expired(self):
        if not self.expires_at:
            return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            from datetime import timezone
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        from datetime import datetime, timezone
        return expires_at < datetime.now(timezone.utc)

    def validate_for_user_and_price(self, user_id, challenge_price):
        from datetime import datetime, timezone
        
        if not self.is_active or self.is_deleted:
            return False, "Coupon is inactive or deleted", 0.0, challenge_price
            
        if self.expires_at:
            expires_at = self.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                return False, "Coupon has expired", 0.0, challenge_price
                
        if self.max_uses is not None and self.used_count >= self.max_uses:
            return False, "Coupon usage limit reached", 0.0, challenge_price
            
        usage_count = CouponUsage.query.filter_by(coupon_id=self.id, user_id=user_id).count()
        if usage_count > 0:
            return False, "You have already used this coupon code", 0.0, challenge_price
            
        if self.coupon_type == 'specific':
            assignment = CouponAssignment.query.filter_by(coupon_id=self.id, user_id=user_id).first()
            if not assignment:
                return False, "This coupon is not assigned to your account", 0.0, challenge_price
            if assignment.is_used:
                return False, "You have already used this assigned coupon code", 0.0, challenge_price
                
        if self.discount_type == 'percent':
            discount_amount = round(challenge_price * (self.discount_value / 100.0), 2)
        elif self.discount_type == 'fixed':
            discount_amount = float(self.discount_value)
        else:
            discount_amount = 0.0
            
        final_price = max(1.0, challenge_price - discount_amount)
        discount_amount = round(challenge_price - final_price, 2)
        
        return True, "Coupon applied successfully", discount_amount, final_price


class CouponUsage(db.Model):
    __tablename__ = 'coupon_usage'
    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False)
    original_price = db.Column(db.Float, nullable=False)
    discount_amount = db.Column(db.Float, nullable=False)
    final_price = db.Column(db.Float, nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    coupon = db.relationship('Coupon', backref=db.backref('usages', lazy=True))
    user = db.relationship('User', backref=db.backref('coupon_usages', lazy=True))
    challenge_purchase = db.relationship('TradingJourney', backref='coupon_usage_obj')


class CouponAssignment(db.Model):
    __tablename__ = 'coupon_assignment'
    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    assigned_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    coupon = db.relationship('Coupon', backref=db.backref('assignments', lazy=True))
    user = db.relationship('User', backref=db.backref('coupon_assignments', lazy=True))