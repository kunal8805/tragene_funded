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
    PENDING_PHASE2 = 'pending_phase2'
    PENDING_FUNDED = 'pending_funded'
    FUNDED = 'funded'
    INACTIVE = 'inactive'
    EXPIRED = 'expired'
    REVOKED = 'revoked'
    
    ALL = [
        PENDING_CREDENTIALS, ACTIVE, PASSED, FAILED, PENDING_PHASE2,
        PENDING_FUNDED, FUNDED, INACTIVE, EXPIRED, REVOKED
    ]


class ProgressionRequestType:
    PHASE2 = 'phase2'
    FUNDED = 'funded'

    ALL = [PHASE2, FUNDED]


class ProgressionRequestStatus:
    PENDING = 'pending'
    APPROVED = 'approved'
    DECLINED = 'declined'

    ALL = [PENDING, APPROVED, DECLINED]

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
    selfie_url = db.Column(db.String(500), default='')
    document_type = db.Column(db.String(20), default='')
    document_number = db.Column(db.String(50), default='')
    kyc_submitted_at = db.Column(db.DateTime(timezone=True), default=None)
    kyc_notes = db.Column(db.Text, default='')

    # Affiliate moderation fields
    affiliate_code = db.Column(db.String(30), unique=True, nullable=True, index=True)
    affiliate_enabled = db.Column(db.Boolean, default=False, index=True)
    affiliate_banned = db.Column(db.Boolean, default=False, index=True)
    affiliate_disabled_reason = db.Column(db.Text, default='')
    affiliate_code_reset_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
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

    # ========================================================================
    # LEAD CRM FIELDS
    # ========================================================================
    lead_status_id = db.Column(db.Integer, db.ForeignKey('lead_statuses.id'), nullable=True, index=True)
    last_contacted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    challenge_purchases = db.relationship('TradingJourney', backref='user_obj', lazy=True, cascade='all, delete-orphan')
    payouts = db.relationship('Payout', backref='user_obj', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='user_obj', lazy=True, cascade='all, delete-orphan', foreign_keys='Payment.user_id')
    reviewed_violations = db.relationship('ViolationEvidence', backref='reviewer', lazy=True, foreign_keys='ViolationEvidence.reviewed_by')
    lead_notes = db.relationship('LeadNote', backref='user', lazy=True, cascade='all, delete-orphan', foreign_keys='LeadNote.user_id')
    follow_ups = db.relationship('FollowUp', backref='user', lazy=True, cascade='all, delete-orphan', foreign_keys='FollowUp.user_id')
    
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
    phase1_daily_dd_type = db.Column(db.String(20), nullable=False, default='equity')
    phase1_overall_loss = db.Column(db.Float, nullable=True)
    phase1_overall_dd_type = db.Column(db.String(20), nullable=False, default='equity')
    phase1_min_days = db.Column(db.Integer, nullable=True)
    phase1_duration = db.Column(db.Integer, nullable=True)
    phase1_leverage = db.Column(db.String(20), nullable=True)
    phase1_rules = db.Column(db.Text, nullable=True)

    # Phase 2 Rules
    phase2_target = db.Column(db.Float, nullable=True)
    phase2_daily_loss = db.Column(db.Float, nullable=True)
    phase2_daily_dd_type = db.Column(db.String(20), nullable=False, default='equity')
    phase2_overall_loss = db.Column(db.Float, nullable=True)
    phase2_overall_dd_type = db.Column(db.String(20), nullable=False, default='equity')
    phase2_min_days = db.Column(db.Integer, nullable=True)
    phase2_duration = db.Column(db.Integer, nullable=True)
    phase2_leverage = db.Column(db.String(20), nullable=True)
    phase2_rules = db.Column(db.Text, nullable=True)

    # Instant Rules
    instant_daily_loss = db.Column(db.Float, nullable=True)
    instant_daily_dd_type = db.Column(db.String(20), nullable=False, default='equity')
    instant_overall_loss = db.Column(db.Float, nullable=True)
    instant_overall_dd_type = db.Column(db.String(20), nullable=False, default='equity')
    instant_min_days = db.Column(db.Integer, nullable=True)
    instant_leverage = db.Column(db.String(20), nullable=True)
    instant_rules = db.Column(db.Text, nullable=True)

    # 🛡️ TRADING SAFETY RULES (NEW)
    sl_mandatory_enabled = db.Column(db.Boolean, default=False)
    sl_grace_period_minutes = db.Column(db.Integer, default=3)
    max_risk_per_trade_percent = db.Column(db.Float, default=1.5)
    activity_rule_enabled = db.Column(db.Boolean, default=False)
    max_inactive_days = db.Column(db.Integer, default=4)

    # ⚖️ LOT SIZE RULES (NEW)
    max_lot_size_enabled = db.Column(db.Boolean, default=False)
    max_lot_size = db.Column(db.Float, default=0.02)
    lot_size_violation_action = db.Column(db.String(20), default='flag')

    user_profit_share = db.Column(db.Integer, nullable=False)
    payout_cycle = db.Column(db.String(20), default='biweekly')
    weekend_trading = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    description = db.Column(db.Text)
    challenge_type = db.Column(db.String(20), nullable=False, default='one_phase', index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
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

    def get_phase_rules(self, phase=None):
        ctype = self.challenge_type or 'one_phase'
        phase = phase if phase is not None else (0 if ctype == 'instant' else 1)
        if ctype == 'instant' or phase == 0:
            return {
                'phase_name': 'Instant',
                'target': 0.0,
                'daily_loss': self.instant_daily_loss or 0.0,
                'daily_dd_type': self.instant_daily_dd_type or 'equity',
                'overall_loss': self.instant_overall_loss or 0.0,
                'overall_dd_type': self.instant_overall_dd_type or 'equity',
                'min_days': self.instant_min_days or 0,
                'duration': 365,
                'leverage': self.instant_leverage or '1:100',
            }
        if ctype == 'two_phase' and phase == 2:
            return {
                'phase_name': 'Phase 2',
                'target': self.phase2_target or 0.0,
                'daily_loss': self.phase2_daily_loss or 0.0,
                'daily_dd_type': self.phase2_daily_dd_type or 'equity',
                'overall_loss': self.phase2_overall_loss or 0.0,
                'overall_dd_type': self.phase2_overall_dd_type or 'equity',
                'min_days': self.phase2_min_days or 0,
                'duration': self.phase2_duration or 30,
                'leverage': self.phase2_leverage or '1:100',
            }
        return {
            'phase_name': 'Phase 1',
            'target': self.phase1_target or 0.0,
            'daily_loss': self.phase1_daily_loss or 0.0,
            'daily_dd_type': self.phase1_daily_dd_type or 'equity',
            'overall_loss': self.phase1_overall_loss or 0.0,
            'overall_dd_type': self.phase1_overall_dd_type or 'equity',
            'min_days': self.phase1_min_days or 0,
            'duration': self.phase1_duration or 30,
            'leverage': self.phase1_leverage or '1:100',
        }

    @staticmethod
    def drawdown_type_label(value):
        return 'Static Balance Based' if value == 'static' else 'Equity Based'

    def get_drawdown_type_label(self, value):
        return self.drawdown_type_label(value)

    def rule_snapshot(self):
        return {
            'id': self.id,
            'name': self.name,
            'account_size': self.account_size,
            'challenge_type': self.challenge_type,
            'phase1': self.get_phase_rules(1),
            'phase2': self.get_phase_rules(2),
            'instant': self.get_phase_rules(0),
            'weekend_trading': self.weekend_trading,
            'profit_split': self.user_profit_share,
            'payout_cycle': self.payout_cycle,
            # 🛡️ Safety rules in snapshot
            'sl_mandatory_enabled': self.sl_mandatory_enabled,
            'sl_grace_period_minutes': self.sl_grace_period_minutes,
            'max_risk_per_trade_percent': self.max_risk_per_trade_percent,
            'activity_rule_enabled': self.activity_rule_enabled,
            'max_inactive_days': self.max_inactive_days,
            'max_lot_size_enabled': self.max_lot_size_enabled,
            'max_lot_size': self.max_lot_size,
            'lot_size_violation_action': self.lot_size_violation_action,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

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
    daily_start_balance = db.Column(db.Float, default=0.0)
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
    day_start_balance = db.Column(db.Float, nullable=True)
    
    # Lifetime lowest equity tracking (never resets)
    lowest_equity_lifetime = db.Column(db.Float, nullable=True)
    lowest_equity_phase = db.Column(db.Float, nullable=True)
    
    # Risk and monitoring
    risk_score = db.Column(db.Integer, default=0)
    monitoring_status = db.Column(db.String(30), default=MonitoringStatus.ACTIVE)
    review_required = db.Column(db.Boolean, default=False)
    
    # Violation review tracking
    violation_reviewed = db.Column(db.Boolean, default=False)
    last_violation_evidence_id = db.Column(db.Integer, nullable=True)
    
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
    phase_day_start_balance = db.Column(db.Float, default=0.0)
    phase_lowest_equity_today = db.Column(db.Float, default=0.0)
    phase_lowest_balance_today = db.Column(db.Float, default=0.0)
    phase_daily_start_date = db.Column(db.Date, nullable=True)

    # Distance metrics
    distance_to_payout = db.Column(db.Float, nullable=True)
    distance_to_breach = db.Column(db.Float, nullable=True)

    # Last trade date
    last_trade_date = db.Column(db.Date, nullable=True)
    
    # 🛡️ SAFETY RULE VIOLATION COUNTERS (NEW)
    sl_violation_count = db.Column(db.Integer, default=0)
    activity_violation_count = db.Column(db.Integer, default=0)
    lot_size_violation_count = db.Column(db.Integer, default=0)
    
    # Tracker for balance manipulation detection
    last_verified_balance = db.Column(db.Float, default=0.0)
    last_verified_equity = db.Column(db.Float, default=0.0)
    last_balance_check_time = db.Column(db.DateTime(timezone=True), nullable=True)
    balance_check_hash = db.Column(db.String(64), default='')
    
    # Fresh start baseline for manipulation checks
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
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    # Relationships
    payouts = db.relationship('Payout', backref='challenge_purchase_obj', lazy=True, cascade='all, delete-orphan')
    payment = db.relationship('Payment', backref='challenge_purchase_obj', uselist=False)
    account_snapshots = db.relationship('AccountSnapshot', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    ea_trades = db.relationship('EATrade', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    rule_violations = db.relationship('RuleViolation', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    violation_evidences = db.relationship('ViolationEvidence', backref='challenge', lazy=True, cascade='all, delete-orphan', foreign_keys='ViolationEvidence.challenge_purchase_id')
    rule_logs = db.relationship('RuleLog', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    trade_history = db.relationship('TradeHistory', backref='challenge_obj', lazy=True, cascade='all, delete-orphan')
    trades = db.relationship('Trade', backref='challenge_purchase_obj', lazy=True)
    coupon_usage = db.relationship('CouponUsage', backref='challenge_purchase_obj', uselist=False)
    progression_requests = db.relationship('ProgressionRequest', backref='challenge_purchase', lazy=True, cascade='all, delete-orphan')
    
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
        
        # Initialize lifetime tracking
        if not self.lowest_equity_lifetime:
            self.lowest_equity_lifetime = float(self.current_equity) if self.current_equity else float(self.starting_equity)
        if not self.lowest_equity_phase:
            self.lowest_equity_phase = float(self.current_equity) if self.current_equity else float(self.starting_equity)
        
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
            'distance_to_breach': self.distance_to_breach,
            'lowest_equity_lifetime': self.lowest_equity_lifetime,
            'lowest_equity_phase': self.lowest_equity_phase,
            'violation_reviewed': self.violation_reviewed,
            # 🛡️ Safety counters
            'sl_violation_count': self.sl_violation_count,
            'activity_violation_count': self.activity_violation_count,
            'lot_size_violation_count': self.lot_size_violation_count
        }
    
    def __repr__(self):
        return f'<ChallengePurchase {self.id} - User {self.user_id}>'

# Alias for backward compatibility
ChallengePurchase = TradingJourney


# ========================================================================
# VIOLATION EVIDENCE SYSTEM (IMMUTABLE FORENSIC RECORDS)
# ========================================================================

class ViolationEvidence(db.Model):
    __tablename__ = 'violation_evidence'
    
    id = db.Column(db.Integer, primary_key=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('account_snapshot.id'), nullable=True)
    
    # Violation Type & Rule
    violation_type = db.Column(db.String(50), nullable=False, index=True)
    rule_name = db.Column(db.String(100), nullable=False)
    rule_limit = db.Column(db.Float, nullable=True)
    actual_value = db.Column(db.Float, nullable=True)
    drawdown_model = db.Column(db.String(30), nullable=True)
    day_start_value = db.Column(db.Float, nullable=True)
    lowest_value = db.Column(db.Float, nullable=True)
    current_value = db.Column(db.Float, nullable=True)
    
    # Account State AT VIOLATION MOMENT (immutable)
    balance = db.Column(db.Float, nullable=True)
    equity = db.Column(db.Float, nullable=True)
    floating_pnl = db.Column(db.Float, nullable=True)
    profit_percent = db.Column(db.Float, nullable=True)
    daily_drawdown = db.Column(db.Float, nullable=True)
    overall_drawdown = db.Column(db.Float, nullable=True)
    trading_days = db.Column(db.Integer, nullable=True)
    
    # Violation Details
    reason = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), default='hard_breach', index=True)
    
    # Forensic Evidence (JSON - stored as dict, never modified)
    open_positions_snapshot = db.Column(db.JSON, nullable=True)
    recent_trades_snapshot = db.Column(db.JSON, nullable=True)
    account_snapshot_data = db.Column(db.JSON, nullable=True)
    
    # Admin Review
    is_reviewed = db.Column(db.Boolean, default=False, index=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    review_decision = db.Column(db.String(50), nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    
    # Timestamps
    violation_timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    snapshot = db.relationship('AccountSnapshot', backref='violation_evidence_refs', foreign_keys=[snapshot_id])
    
    __table_args__ = (
        Index('idx_ve_challenge_type', 'challenge_purchase_id', 'violation_type'),
        Index('idx_ve_challenge_created', 'challenge_purchase_id', 'created_at'),
        Index('idx_ve_reviewed', 'is_reviewed', 'violation_type'),
        Index('idx_ve_severity', 'severity', 'created_at'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'challenge_purchase_id': self.challenge_purchase_id,
            'violation_type': self.violation_type,
            'rule_name': self.rule_name,
            'rule_limit': self.rule_limit,
            'actual_value': self.actual_value,
            'drawdown_model': self.drawdown_model,
            'day_start_value': self.day_start_value,
            'lowest_value': self.lowest_value,
            'current_value': self.current_value,
            'balance': self.balance,
            'equity': self.equity,
            'floating_pnl': self.floating_pnl,
            'profit_percent': self.profit_percent,
            'daily_drawdown': self.daily_drawdown,
            'overall_drawdown': self.overall_drawdown,
            'reason': self.reason,
            'severity': self.severity,
            'open_positions_snapshot': self.open_positions_snapshot,
            'recent_trades_snapshot': self.recent_trades_snapshot,
            'account_snapshot_data': self.account_snapshot_data,
            'is_reviewed': self.is_reviewed,
            'review_decision': self.review_decision,
            'review_notes': self.review_notes,
            'violation_timestamp': self.violation_timestamp.isoformat() if self.violation_timestamp else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<ViolationEvidence {self.id} - {self.violation_type} - Challenge {self.challenge_purchase_id}>'


# ========================================================================
# NOTIFICATION CENTER / EMAIL PLATFORM MODELS
# ========================================================================

class EmailTemplate(db.Model):
    __tablename__ = 'email_template'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    category = db.Column(db.String(40), default='transactional', index=True)
    subject = db.Column(db.String(255), nullable=False)
    html_body = db.Column(db.Text, nullable=False)
    text_body = db.Column(db.Text, nullable=True)
    variables = db.Column(db.JSON, nullable=True)
    channel = db.Column(db.String(30), default='email', index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    creator = db.relationship('User', foreign_keys=[created_by])
    updater = db.relationship('User', foreign_keys=[updated_by])

    def __repr__(self):
        return f'<EmailTemplate {self.slug}>'


class EmailAutomationRule(db.Model):
    __tablename__ = 'email_automation_rule'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    event = db.Column(db.String(80), nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=True)
    subject_override = db.Column(db.String(255), nullable=True)
    html_override = db.Column(db.Text, nullable=True)
    channel = db.Column(db.String(30), default='email', index=True)
    is_enabled = db.Column(db.Boolean, default=True, index=True)
    is_paused = db.Column(db.Boolean, default=False, index=True)
    is_system = db.Column(db.Boolean, default=False)
    once_scope = db.Column(db.String(40), default='none')  # none, user, challenge
    description = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    template = db.relationship('EmailTemplate', backref=db.backref('automations', lazy=True))

    def __repr__(self):
        return f'<EmailAutomationRule {self.key}>'


class EmailCampaign(db.Model):
    __tablename__ = 'email_campaign'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    campaign_type = db.Column(db.String(50), default='general', index=True)
    subject = db.Column(db.String(255), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=True)
    audience_type = db.Column(db.String(80), default='all_users', index=True)
    audience_filters = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(30), default='draft', index=True)
    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    recurring_rule = db.Column(db.String(30), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)

    template = db.relationship('EmailTemplate', backref=db.backref('campaigns', lazy=True))
    creator = db.relationship('User', foreign_keys=[created_by])

    def __repr__(self):
        return f'<EmailCampaign {self.name}>'


class EmailCampaignRecipient(db.Model):
    __tablename__ = 'email_campaign_recipient'
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('email_campaign.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    email = db.Column(db.String(160), nullable=False, index=True)
    status = db.Column(db.String(30), default='pending', index=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    skipped_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    campaign = db.relationship('EmailCampaign', backref=db.backref('recipients', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])


class EmailLog(db.Model):
    __tablename__ = 'email_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    to_email = db.Column(db.String(160), nullable=False, index=True)
    subject = db.Column(db.String(255), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=True, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('email_campaign.id'), nullable=True, index=True)
    automation_id = db.Column(db.Integer, db.ForeignKey('email_automation_rule.id'), nullable=True, index=True)
    channel = db.Column(db.String(30), default='email', index=True)
    status = db.Column(db.String(30), default='pending', index=True)
    provider = db.Column(db.String(50), default='resend')
    provider_message_id = db.Column(db.String(160), nullable=True, index=True)
    dedupe_key = db.Column(db.String(220), nullable=True, index=True)
    failed_reason = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    delivered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    opened_at = db.Column(db.DateTime(timezone=True), nullable=True)
    clicked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    bounced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship('User', foreign_keys=[user_id])
    template = db.relationship('EmailTemplate')
    campaign = db.relationship('EmailCampaign')
    automation = db.relationship('EmailAutomationRule')

    __table_args__ = (
        Index('idx_email_log_status_created', 'status', 'created_at'),
        Index('idx_email_log_dedupe', 'dedupe_key', 'status'),
    )


class EmailPreference(db.Model):
    __tablename__ = 'email_preference'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False, index=True)
    allow_emails = db.Column(db.Boolean, default=True)
    disable_marketing = db.Column(db.Boolean, default=False)
    disable_campaigns = db.Column(db.Boolean, default=False)
    disable_all = db.Column(db.Boolean, default=False)
    admin_override = db.Column(db.Boolean, default=False)
    blocked = db.Column(db.Boolean, default=False, index=True)
    blocked_reason = db.Column(db.String(255), default='')
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('email_preference', uselist=False))


class ScheduledEmail(db.Model):
    __tablename__ = 'scheduled_email'
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('email_campaign.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    to_email = db.Column(db.String(160), nullable=True)
    subject = db.Column(db.String(255), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=True)
    html_body = db.Column(db.Text, nullable=True)
    variables = db.Column(db.JSON, nullable=True)
    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    recurring_rule = db.Column(db.String(30), nullable=True)
    status = db.Column(db.String(30), default='pending', index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    campaign = db.relationship('EmailCampaign')
    user = db.relationship('User', foreign_keys=[user_id])
    template = db.relationship('EmailTemplate')


class EmailCampaignAnalytics(db.Model):
    __tablename__ = 'email_campaign_analytics'
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('email_campaign.id'), nullable=True, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=True, index=True)
    automation_id = db.Column(db.Integer, db.ForeignKey('email_automation_rule.id'), nullable=True, index=True)
    metric_date = db.Column(db.Date, nullable=False, index=True)
    sent = db.Column(db.Integer, default=0)
    delivered = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    bounced = db.Column(db.Integer, default=0)
    opened = db.Column(db.Integer, default=0)
    clicked = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    campaign = db.relationship('EmailCampaign')
    template = db.relationship('EmailTemplate')
    automation = db.relationship('EmailAutomationRule')


# ========================================================================
# [ALL REMAINING MODELS UNCHANGED - KEEP EXACTLY AS ORIGINAL]
# ========================================================================

class ProgressionRequest(db.Model):
    __tablename__ = 'progression_requests'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=False, index=True)
    request_type = db.Column(db.String(20), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=ProgressionRequestStatus.PENDING, index=True)
    admin_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    declined_at = db.Column(db.DateTime(timezone=True), nullable=True)
    user = db.relationship('User', backref=db.backref('progression_requests', lazy=True, cascade='all, delete-orphan'))
    __table_args__ = (
        Index('idx_progression_request_user_status', 'user_id', 'status'),
        Index('idx_progression_request_challenge_type_status', 'challenge_purchase_id', 'request_type', 'status'),
    )
    def __repr__(self):
        return f'<ProgressionRequest {self.id} - {self.request_type} - {self.status}>'

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
    def is_manual_trade(self): return self.magic == 0
    def is_bot_trade(self): return self.magic > 0
    def __repr__(self): return f'<EATrade {self.ticket} - {self.symbol} - {self.status}>'

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
    def __repr__(self): return f'<RuleViolation {self.rule_name} - Challenge {self.challenge_purchase_id}>'
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
    def __repr__(self): return f'<DailySnapshot {self.snapshot_date} - Challenge {self.challenge_purchase_id}>'

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
    user = db.relationship('User', backref='payouts_list', foreign_keys=[user_id])
    challenge_purchase = db.relationship('TradingJourney', backref='payouts_list', foreign_keys=[challenge_purchase_id])
    def __repr__(self): return f'<Payout {self.id} - ${self.amount}>'

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
    def __repr__(self): return f'<PayoutAuditLog {self.action} - Payout {self.payout_id}>'

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
    affiliate_code = db.Column(db.String(30), nullable=True, index=True)
    affiliate_discount_amount = db.Column(db.Float, default=0.0)
    visible_to_partner = db.Column(db.Boolean, default=False, nullable=False, index=True)
    rule_acceptance_timestamp = db.Column(db.DateTime(timezone=True), nullable=True)
    rule_acceptance_ip = db.Column(db.String(50), nullable=True)
    rule_acceptance_user_agent = db.Column(db.Text, nullable=True)
    challenge_version_snapshot = db.Column(db.JSON, nullable=True)
    rule_version_snapshot = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user = db.relationship('User', backref='payments_list', foreign_keys=[user_id])
    challenge_purchase = db.relationship('TradingJourney', backref='payment_obj', foreign_keys=[challenge_purchase_id])
    coupon = db.relationship('Coupon', backref='payments_list')
    def __repr__(self): return f'<Payment {self.payment_id} - {self.status}>'

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
    def __repr__(self): return f'<WebhookLog {self.event_type} - {self.order_id} - {self.status}>'

class RulebookSection(db.Model):
    __tablename__ = 'rulebook_section'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=0, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    creator = db.relationship('User', foreign_keys=[created_by])
    def __repr__(self): return f'<RulebookSection {self.display_order} - {self.title}>'

class PurchaseRuleAcceptance(db.Model):
    __tablename__ = 'purchase_rule_acceptance'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    challenge_template_id = db.Column(db.Integer, db.ForeignKey('challenge_template.id'), nullable=False, index=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=True, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=True, index=True)
    accepted_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    ip_address = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    challenge_version_snapshot = db.Column(db.JSON, nullable=False)
    rule_version_snapshot = db.Column(db.String(50), nullable=False, default='rulebook-v1')
    user = db.relationship('User', foreign_keys=[user_id])
    challenge_template = db.relationship('ChallengeTemplate', foreign_keys=[challenge_template_id])
    challenge_purchase = db.relationship('TradingJourney', foreign_keys=[challenge_purchase_id], backref=db.backref('rule_acceptances', lazy=True))
    payment = db.relationship('Payment', foreign_keys=[payment_id], backref=db.backref('rule_acceptance', uselist=False))
    def __repr__(self): return f'<PurchaseRuleAcceptance user={self.user_id} challenge={self.challenge_template_id}>'

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
    def __repr__(self): return f'<AdminLog {self.action} by {self.admin_id}>'

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
    def __repr__(self): return f'<AdminAuditLog {self.action} by {self.admin_id}>'

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
    def __repr__(self): return f'<SupportTicket {self.ticket_number} - {self.subject}>'

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
    def __repr__(self): return f'<TicketMessage {self.id} for Ticket {self.ticket_id}>'

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
    def __repr__(self): return f'<FAQ {self.question[:30]}>'

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
    def __repr__(self): return f'<Trade {self.trade_id} - {self.symbol}>'

class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default='system', index=True)
    action_url = db.Column(db.String(500), nullable=True)
    icon = db.Column(db.String(50), nullable=True)
    dedupe_key = db.Column(db.String(120), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    is_global = db.Column(db.Boolean, default=True, index=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, index=True)
    target_user = db.relationship('User', foreign_keys=[target_user_id], backref='targeted_notifications', lazy=True)
    admin = db.relationship('User', foreign_keys=[created_by_admin_id], backref='created_notifications', lazy=True)
    def __repr__(self): return f'<Notification {self.id} - {self.title}>'

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
    def increment_use_count(self): self.use_count += 1
    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'title': self.title, 'message': self.message, 'category': self.category, 'is_active': self.is_active, 'use_count': self.use_count, 'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None}
    def __repr__(self): return f'<NotificationTemplate {self.name} - {self.category}>'

class UserNotification(db.Model):
    __tablename__ = 'user_notification'
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notification.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    notification = db.relationship('Notification', backref=db.backref('user_statuses', cascade='all, delete-orphan', lazy=True))
    user = db.relationship('User', backref=db.backref('read_statuses', cascade='all, delete-orphan', lazy=True))
    def __repr__(self): return f'<UserNotification {self.id} - User {self.user_id} - Read: {self.is_read}>'

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
    def __repr__(self): return f'<WaitlistLead {self.email}>'

class BlogPost(db.Model):
    __tablename__ = 'blog_posts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    meta_description = db.Column(db.String(255), nullable=False)
    date_published = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    def __repr__(self): return f'<BlogPost {self.title}>'

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
        if not self.expires_at: return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            from datetime import timezone
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        from datetime import datetime, timezone
        return expires_at < datetime.now(timezone.utc)
    def validate_for_user_and_price(self, user_id, challenge_price):
        from datetime import datetime, timezone
        if not self.is_active or self.is_deleted: return False, "Coupon is inactive or deleted", 0.0, challenge_price
        if self.expires_at:
            expires_at = self.expires_at
            if expires_at.tzinfo is None: expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc): return False, "Coupon has expired", 0.0, challenge_price
        if self.max_uses is not None and self.used_count >= self.max_uses: return False, "Coupon usage limit reached", 0.0, challenge_price
        usage_count = CouponUsage.query.filter_by(coupon_id=self.id, user_id=user_id).count()
        if usage_count > 0: return False, "You have already used this coupon code", 0.0, challenge_price
        if self.coupon_type == 'specific':
            assignment = CouponAssignment.query.filter_by(coupon_id=self.id, user_id=user_id).first()
            if not assignment: return False, "This coupon is not assigned to your account", 0.0, challenge_price
            if assignment.is_used: return False, "You have already used this assigned coupon code", 0.0, challenge_price
        if self.discount_type == 'percent': discount_amount = round(challenge_price * (self.discount_value / 100.0), 2)
        elif self.discount_type == 'fixed': discount_amount = float(self.discount_value)
        else: discount_amount = 0.0
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

class AffiliateSettings(db.Model):
    __tablename__ = 'affiliate_settings'
    id = db.Column(db.Integer, primary_key=True)
    buyer_discount_amount = db.Column(db.Float, default=0.0, nullable=False)
    referrer_reward_amount = db.Column(db.Float, default=0.0, nullable=False)
    minimum_withdrawal_amount = db.Column(db.Float, default=150.0, nullable=False)
    affiliate_enabled = db.Column(db.Boolean, default=True, nullable=False)
    cash_withdrawal_enabled = db.Column(db.Boolean, default=False, nullable=False)
    coupon_conversion_enabled = db.Column(db.Boolean, default=False, nullable=False)
    updated_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    @classmethod
    def get_settings(cls):
        settings = cls.query.order_by(cls.id.asc()).first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.flush()
        return settings

class Wallet(db.Model):
    __tablename__ = 'wallet'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)
    current_balance = db.Column(db.Float, default=0.0, nullable=False)
    lifetime_earned = db.Column(db.Float, default=0.0, nullable=False)
    lifetime_withdrawn = db.Column(db.Float, default=0.0, nullable=False)
    pending_balance = db.Column(db.Float, default=0.0, nullable=False)
    is_frozen = db.Column(db.Boolean, default=False, nullable=False, index=True)
    frozen_reason = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user = db.relationship('User', backref=db.backref('wallet', uselist=False, cascade='all, delete-orphan'))
    @classmethod
    def get_or_create(cls, user_id):
        wallet = cls.query.filter_by(user_id=user_id).first()
        if not wallet:
            wallet = cls(user_id=user_id)
            db.session.add(wallet)
            db.session.flush()
        return wallet
    @property
    def withdrawable_amount(self):
        return max(0.0, float(self.current_balance or 0) - float(self.pending_balance or 0))

class WalletTransaction(db.Model):
    __tablename__ = 'wallet_transaction'
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False, index=True)
    source = db.Column(db.String(30), nullable=False, index=True)
    status = db.Column(db.String(20), default='completed', nullable=False, index=True)
    reference_type = db.Column(db.String(50), default='')
    reference_id = db.Column(db.Integer, nullable=True, index=True)
    notes = db.Column(db.Text, default='')
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    wallet = db.relationship('Wallet', backref=db.backref('transactions', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('wallet_transactions', lazy=True))
    admin = db.relationship('User', foreign_keys=[admin_id])

class ReferralReward(db.Model):
    __tablename__ = 'referral_reward'
    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=True, index=True)
    challenge_purchase_id = db.Column(db.Integer, db.ForeignKey('challenge_purchase.id'), nullable=True, index=True)
    affiliate_code = db.Column(db.String(30), nullable=False, index=True)
    purchase_amount = db.Column(db.Float, default=0.0, nullable=False)
    discount_given = db.Column(db.Float, default=0.0, nullable=False)
    reward_given = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    violation_id = db.Column(db.Integer, db.ForeignKey('affiliate_violation.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    referrer = db.relationship('User', foreign_keys=[referrer_id], backref=db.backref('referral_rewards', lazy=True))
    buyer = db.relationship('User', foreign_keys=[buyer_id], backref=db.backref('referral_purchases', lazy=True))
    payment = db.relationship('Payment', backref=db.backref('referral_reward', uselist=False))
    challenge_purchase = db.relationship('TradingJourney')

class WithdrawalRequest(db.Model):
    __tablename__ = 'withdrawal_request'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    upi_id = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    admin_notes = db.Column(db.Text, default='')
    transaction_id = db.Column(db.String(120), default='')
    requested_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewed_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('withdrawal_requests', lazy=True))
    wallet = db.relationship('Wallet', backref=db.backref('withdrawal_requests', lazy=True))
    admin = db.relationship('User', foreign_keys=[reviewed_by_admin_id])

class Survey(db.Model):
    __tablename__ = 'survey'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    survey_type = db.Column(db.String(20), nullable=False, default='text', index=True)
    reward_amount = db.Column(db.Float, default=0.0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    questions = db.relationship('SurveyQuestion', backref='survey', lazy=True, cascade='all, delete-orphan')
    assignments = db.relationship('SurveyAssignment', backref='survey', lazy=True, cascade='all, delete-orphan')

class SurveyQuestion(db.Model):
    __tablename__ = 'survey_question'
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False, index=True)
    question_text = db.Column(db.Text, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)

class SurveyAssignment(db.Model):
    __tablename__ = 'survey_assignment'
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    status = db.Column(db.String(30), default='assigned', nullable=False, index=True)
    assigned_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    responded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rewarded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reward_transaction_id = db.Column(db.Integer, db.ForeignKey('wallet_transaction.id'), nullable=True)
    user = db.relationship('User', backref=db.backref('survey_assignments', lazy=True))
    reward_transaction = db.relationship('WalletTransaction')

class SurveyResponse(db.Model):
    __tablename__ = 'survey_response'
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('survey_assignment.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('survey_question.id'), nullable=True, index=True)
    response_text = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    assignment = db.relationship('SurveyAssignment', backref=db.backref('responses', lazy=True, cascade='all, delete-orphan'))
    question = db.relationship('SurveyQuestion')

class AffiliateViolation(db.Model):
    __tablename__ = 'affiliate_violation'
    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    affiliate_code = db.Column(db.String(30), nullable=True, index=True)
    violation_type = db.Column(db.String(50), nullable=False, index=True)
    severity = db.Column(db.String(20), default='medium', nullable=False, index=True)
    details = db.Column(db.Text, default='')
    ip_address = db.Column(db.String(50), default='', index=True)
    is_resolved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    referrer = db.relationship('User', foreign_keys=[referrer_id], backref=db.backref('affiliate_violations_as_referrer', lazy=True))
    buyer = db.relationship('User', foreign_keys=[buyer_id], backref=db.backref('affiliate_violations_as_buyer', lazy=True))
    resolver = db.relationship('User', foreign_keys=[resolved_by_admin_id])

class LeadStatus(db.Model):
    __tablename__ = 'lead_statuses'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, index=True)
    color = db.Column(db.String(7), default='#6B7280')
    is_default = db.Column(db.Boolean, default=False)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    users = db.relationship('User', backref='lead_status', lazy='dynamic', foreign_keys='User.lead_status_id')
    DEFAULT_STATUSES = [
        {'name': 'New Lead', 'color': '#3B82F6', 'order': 1},
        {'name': 'Call Follow-up', 'color': '#F59E0B', 'order': 2},
        {'name': 'WhatsApp Follow-up', 'color': '#10B981', 'order': 3},
        {'name': 'Email Follow-up', 'color': '#8B5CF6', 'order': 4},
        {'name': 'Interested', 'color': '#EC4899', 'order': 5},
        {'name': 'Purchased', 'color': '#059669', 'order': 6},
        {'name': 'KYC Applied', 'color': '#6366F1', 'order': 7},
        {'name': 'KYC Verified', 'color': '#0891B2', 'order': 8},
        {'name': 'Dead Lead', 'color': '#6B7280', 'order': 9},
    ]
    @classmethod
    def create_defaults(cls):
        for status_data in cls.DEFAULT_STATUSES:
            existing = cls.query.filter_by(name=status_data['name']).first()
            if not existing:
                status = cls(name=status_data['name'], color=status_data['color'], is_default=True, display_order=status_data['order'])
                db.session.add(status)
        db.session.commit()
    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'color': self.color, 'is_default': self.is_default, 'display_order': self.display_order, 'lead_count': self.users.count()}
    def __repr__(self): return f'<LeadStatus {self.name}>'

class LeadNote(db.Model):
    __tablename__ = 'lead_notes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_edited = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    admin = db.relationship('User', foreign_keys=[admin_id], backref='admin_lead_notes')
    def to_dict(self):
        return {'id': self.id, 'user_id': self.user_id, 'admin_id': self.admin_id, 'content': self.content, 'is_edited': self.is_edited, 'created_at': self.created_at.isoformat() if self.created_at else None, 'updated_at': self.updated_at.isoformat() if self.updated_at else None, 'admin_name': self.admin.get_full_name() if self.admin else 'Unknown'}
    def __repr__(self): return f'<LeadNote {self.id} - User {self.user_id}>'

class FollowUp(db.Model):
    __tablename__ = 'follow_ups'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    followup_date = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    followup_type = db.Column(db.String(20), nullable=False, default='Call')
    notes = db.Column(db.Text, default='')
    is_completed = db.Column(db.Boolean, default=False, index=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    admin = db.relationship('User', foreign_keys=[admin_id], backref='admin_follow_ups')
    __table_args__ = (Index('idx_followup_user_date', 'user_id', 'followup_date'), Index('idx_followup_completed', 'is_completed', 'followup_date'))
    def to_dict(self):
        return {'id': self.id, 'user_id': self.user_id, 'admin_id': self.admin_id, 'followup_date': self.followup_date.isoformat() if self.followup_date else None, 'followup_type': self.followup_type, 'notes': self.notes, 'is_completed': self.is_completed, 'completed_at': self.completed_at.isoformat() if self.completed_at else None, 'created_at': self.created_at.isoformat() if self.created_at else None, 'admin_name': self.admin.get_full_name() if self.admin else 'Unknown'}
    def __repr__(self): return f'<FollowUp {self.id} - User {self.user_id} - {self.followup_type}>'
class SiteSettings(db.Model):
    """Global site settings - SINGLE ROW (singleton pattern)"""
    __tablename__ = 'site_settings'
    id = db.Column(db.Integer, primary_key=True)
    marketplace_locked = db.Column(db.Boolean, default=False, nullable=False)
    marketplace_lock_reason = db.Column(db.String(500), default='')
    marketplace_locked_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    marketplace_locked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # Relationship to know which admin locked it
    locked_by_admin = db.relationship('User', foreign_keys=[marketplace_locked_by])
    @classmethod
    def get_settings(cls):
        """Always returns the ONE settings row (creates if not exists)"""
        settings = cls.query.first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.flush()
        return settings

# ========================================================================
# SINGLE SOURCE OF TRUTH: statuses eligible for MT5 sync + rule processing
# Add new statuses HERE ONLY. Both mt5_receiver.py and rule_engine.py import this.
# ========================================================================
SYNC_ELIGIBLE_STATUSES = [
    'active',
    'funded',
    'under_review',
    'phase1_active',
    'phase2_active',
    'funded_active',
]
