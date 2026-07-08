import csv
import io
import os
import re
from datetime import datetime, timedelta, timezone

from flask import url_for

from models import (
    db,
    User,
    ChallengePurchase,
    EmailAutomationRule,
    EmailCampaign,
    EmailCampaignAnalytics,
    EmailCampaignRecipient,
    EmailLog,
    EmailPreference,
    EmailTemplate,
    ScheduledEmail,
)

try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    resend = None
    RESEND_AVAILABLE = False


DEFAULT_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "Tragene Funded <support@tragenefunded.com>")
COMPANY_NAME = "Tragene Funded"
PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")

TEMPLATE_CATEGORIES = ["transactional", "marketing", "support", "challenge", "kyc", "promotion", "newsletter"]
CAMPAIGN_TYPES = ["newsletter", "promotion", "coupon", "announcement", "maintenance", "challenge_launch", "general"]
AUDIENCE_TYPES = [
    "all_users", "verified_users", "unverified_users", "kyc_pending", "kyc_approved",
    "purchased_users", "never_purchased", "challenge_active", "challenge_failed",
    "challenge_passed", "specific_user", "multiple_users", "partner_users", "admins",
    "inactive_users", "new_users", "registered_today", "registered_last_7_days",
    "registered_last_30_days",
]


def configure_resend():
    api_key = os.getenv("RESEND_API_KEY")
    if RESEND_AVAILABLE and api_key:
        resend.api_key = api_key
        return True
    return False


def render_placeholders(content, variables=None):
    variables = variables or {}

    def repl(match):
        key = match.group(1)
        value = variables.get(key, "")
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(repl, content or "")


def default_variables(user=None, challenge=None, **extra):
    today = datetime.now(timezone.utc).strftime("%d %b %Y")
    data = {
        "name": user.get_full_name() if user and hasattr(user, "get_full_name") else (f"{user.first_name} {user.last_name}" if user else ""),
        "first_name": user.first_name if user else "",
        "last_name": user.last_name if user else "",
        "email": user.email if user else "",
        "company_name": COMPANY_NAME,
        "date": today,
        "dashboard_url": extra.get("dashboard_url") or "/user/dashboard",
        "evidence_url": extra.get("evidence_url") or "/user/history",
        "challenge": "",
        "account_size": "",
        "order_id": extra.get("order_id", ""),
    }
    if challenge:
        template = getattr(challenge, "challenge_template", None)
        data.update({
            "challenge": template.name if template else "Challenge",
            "account_size": getattr(template, "account_size", "") if template else "",
            "evidence_url": extra.get("evidence_url") or f"/user/history/details/{challenge.id}",
        })
    data.update(extra)
    return data


def get_or_create_preferences(user_id):
    pref = EmailPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = EmailPreference(user_id=user_id)
        db.session.add(pref)
        db.session.flush()
    return pref


def can_send_to_user(user, email_type="transactional", ignore_preferences=False):
    if not user or ignore_preferences:
        return True, ""
    pref = get_or_create_preferences(user.id)
    if pref.admin_override:
        return True, ""
    if pref.blocked:
        return False, pref.blocked_reason or "Recipient is blocked"
    if pref.disable_all or not pref.allow_emails:
        return False, "User has disabled emails"
    if email_type in ("marketing", "promotion", "newsletter") and pref.disable_marketing:
        return False, "User has disabled marketing emails"
    if email_type == "campaign" and pref.disable_campaigns:
        return False, "User has disabled campaign emails"
    return True, ""


def _log_email(to_email, subject, status="pending", user=None, template=None, campaign=None,
               automation=None, dedupe_key=None, failed_reason=None):
    log = EmailLog(
        user_id=user.id if user else None,
        to_email=to_email,
        subject=subject,
        template_id=template.id if template else None,
        campaign_id=campaign.id if campaign else None,
        automation_id=automation.id if automation else None,
        status=status,
        dedupe_key=dedupe_key,
        failed_reason=failed_reason,
    )
    db.session.add(log)
    db.session.flush()
    return log


def send_email(to_email, subject, html_body, user=None, template=None, campaign=None,
               automation=None, variables=None, dedupe_key=None, email_type="transactional",
               ignore_preferences=False):
    if dedupe_key:
        existing = EmailLog.query.filter(
            EmailLog.dedupe_key == dedupe_key,
            EmailLog.status.in_(["sent", "delivered", "pending"])
        ).first()
        if existing:
            return existing

    allowed, reason = can_send_to_user(user, email_type=email_type, ignore_preferences=ignore_preferences)
    if not allowed:
        log = _log_email(to_email, subject, "skipped", user, template, campaign, automation, dedupe_key, reason)
        db.session.commit()
        return log

    rendered_subject = render_placeholders(subject, variables)
    rendered_html = render_placeholders(html_body, variables)
    log = _log_email(to_email, rendered_subject, "pending", user, template, campaign, automation, dedupe_key)

    if not configure_resend():
        log.status = "failed"
        log.failed_reason = "Resend is not configured"
        db.session.commit()
        return log

    try:
        result = resend.Emails.send({
            "from": DEFAULT_FROM_EMAIL,
            "to": [to_email],
            "subject": rendered_subject,
            "html": rendered_html,
        })
        log.status = "sent"
        log.sent_at = datetime.now(timezone.utc)
        if isinstance(result, dict):
            log.provider_message_id = result.get("id") or result.get("message_id")
        else:
            log.provider_message_id = str(result)
    except Exception as exc:
        log.status = "failed"
        log.failed_reason = str(exc)
    db.session.commit()
    return log


def send_template_email(template_slug, user, variables=None, dedupe_key=None, email_type="transactional"):
    template = EmailTemplate.query.filter_by(slug=template_slug, is_active=True).first()
    if not template:
        return send_email(user.email, f"{COMPANY_NAME} Update", "Email template is not configured.", user=user, dedupe_key=dedupe_key)
    merged = default_variables(user, **(variables or {}))
    return send_email(
        user.email,
        template.subject,
        template.html_body,
        user=user,
        template=template,
        variables=merged,
        dedupe_key=dedupe_key,
        email_type=email_type,
    )


def send_automation_email(key, user, variables=None, challenge=None, force=False):
    automation = EmailAutomationRule.query.filter_by(key=key).first()
    if not automation or (not force and (not automation.is_enabled or automation.is_paused)):
        return None

    template = automation.template
    subject = automation.subject_override or (template.subject if template else f"{COMPANY_NAME} Update")
    html = automation.html_override or (template.html_body if template else "<p>{{name}}, there is an update on your account.</p>")
    scope_value = user.id
    if automation.once_scope == "challenge" and challenge:
        scope_value = challenge.id
    dedupe_key = None
    if automation.once_scope in ("user", "challenge"):
        dedupe_key = f"automation:{automation.key}:{scope_value}"
    elif challenge:
        dedupe_key = f"automation:{automation.key}:{challenge.id}:{datetime.now(timezone.utc).date().isoformat()}"

    merged = default_variables(user, challenge, **(variables or {}))
    return send_email(
        user.email,
        subject,
        html,
        user=user,
        template=template,
        automation=automation,
        variables=merged,
        dedupe_key=dedupe_key,
        email_type="transactional",
    )


def audience_query(audience_type, filters=None):
    filters = filters or {}
    q = User.query
    now = datetime.now(timezone.utc)
    if audience_type == "verified_users":
        q = q.filter_by(email_verified=True)
    elif audience_type == "unverified_users":
        q = q.filter_by(email_verified=False)
    elif audience_type == "kyc_pending":
        q = q.filter(User.kyc_status.in_(["pending", "submitted"]))
    elif audience_type == "kyc_approved":
        q = q.filter_by(kyc_status="approved")
    elif audience_type == "purchased_users":
        q = q.join(ChallengePurchase, ChallengePurchase.user_id == User.id).distinct()
    elif audience_type == "never_purchased":
        purchased = db.session.query(ChallengePurchase.user_id)
        q = q.filter(~User.id.in_(purchased))
    elif audience_type == "challenge_active":
        q = q.join(ChallengePurchase, ChallengePurchase.user_id == User.id).filter(ChallengePurchase.status.in_(["active", "phase1_active", "phase2_active", "funded_active"])).distinct()
    elif audience_type == "challenge_failed":
        q = q.join(ChallengePurchase, ChallengePurchase.user_id == User.id).filter(ChallengePurchase.status == "failed").distinct()
    elif audience_type == "challenge_passed":
        q = q.join(ChallengePurchase, ChallengePurchase.user_id == User.id).filter(ChallengePurchase.status == "passed").distinct()
    elif audience_type == "partner_users":
        q = q.filter(User.role == "partner")
    elif audience_type == "admins":
        q = q.filter_by(is_admin=True)
    elif audience_type == "inactive_users":
        q = q.filter(User.created_at <= now - timedelta(days=30))
    elif audience_type == "new_users":
        q = q.filter(User.created_at >= now - timedelta(days=7))
    elif audience_type == "registered_today":
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        q = q.filter(User.created_at >= start)
    elif audience_type == "registered_last_7_days":
        q = q.filter(User.created_at >= now - timedelta(days=7))
    elif audience_type == "registered_last_30_days":
        q = q.filter(User.created_at >= now - timedelta(days=30))
    elif audience_type == "specific_user":
        user_id = filters.get("user_id")
        email = filters.get("email")
        if user_id:
            q = q.filter(User.id == int(user_id))
        elif email:
            q = q.filter(User.email == email)
        else:
            q = q.filter(User.id == -1)
    elif audience_type == "multiple_users":
        ids = filters.get("user_ids") or []
        emails = filters.get("emails") or []
        if isinstance(ids, str):
            ids = [x.strip() for x in ids.split(",") if x.strip()]
        if isinstance(emails, str):
            emails = [x.strip().lower() for x in emails.split(",") if x.strip()]
        q = q.filter(db.or_(User.id.in_(ids or [-1]), User.email.in_(emails or [""])))
    return q


def resolve_audience(audience_type, filters=None):
    return audience_query(audience_type, filters).order_by(User.created_at.desc()).all()


def send_campaign(campaign):
    if isinstance(campaign, int):
        campaign = EmailCampaign.query.get(campaign)
    if not campaign or campaign.status in ("archived", "deleted"):
        return 0
    template = campaign.template
    if not template:
        return 0

    recipients = resolve_audience(campaign.audience_type, campaign.audience_filters)
    sent = 0
    for user in recipients:
        dedupe_key = f"campaign:{campaign.id}:{user.id}"
        recipient = EmailCampaignRecipient.query.filter_by(campaign_id=campaign.id, user_id=user.id).first()
        if not recipient:
            recipient = EmailCampaignRecipient(campaign_id=campaign.id, user_id=user.id, email=user.email)
            db.session.add(recipient)
            db.session.flush()
        log = send_email(
            user.email,
            campaign.subject or template.subject,
            template.html_body,
            user=user,
            template=template,
            campaign=campaign,
            variables=default_variables(user),
            dedupe_key=dedupe_key,
            email_type="campaign",
        )
        recipient.status = log.status
        recipient.sent_at = log.sent_at
        recipient.skipped_reason = log.failed_reason
        if log.status == "sent":
            sent += 1
    campaign.status = "sent"
    db.session.commit()
    rebuild_daily_analytics()
    return sent


def stats_snapshot():
    now = datetime.now(timezone.utc)
    start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    start_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    total = EmailLog.query.count()
    sent = EmailLog.query.filter(EmailLog.status.in_(["sent", "delivered"])).count()
    failed = EmailLog.query.filter_by(status="failed").count()
    pending = EmailLog.query.filter_by(status="pending").count()
    bounced = EmailLog.query.filter(EmailLog.bounced_at.isnot(None)).count()
    opened = EmailLog.query.filter(EmailLog.opened_at.isnot(None)).count()
    clicked = EmailLog.query.filter(EmailLog.clicked_at.isnot(None)).count()
    return {
        "total": total,
        "sent": sent,
        "today": EmailLog.query.filter(EmailLog.created_at >= start_today).count(),
        "month": EmailLog.query.filter(EmailLog.created_at >= start_month).count(),
        "failed": failed,
        "pending": pending,
        "delivery_rate": round((sent / total * 100), 2) if total else 0,
        "success_rate": round((sent / max(sent + failed, 1) * 100), 2) if total else 0,
        "bounce_rate": round((bounced / total * 100), 2) if total else 0,
        "open_rate": round((opened / total * 100), 2) if total else 0,
        "click_rate": round((clicked / total * 100), 2) if total else 0,
        "active_automations": EmailAutomationRule.query.filter_by(is_enabled=True, is_paused=False).count(),
        "active_campaigns": EmailCampaign.query.filter(EmailCampaign.status.in_(["scheduled", "sending", "draft"])).count(),
    }


def chart_counts(days=30):
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        rows.append({
            "label": day.strftime("%d %b"),
            "count": EmailLog.query.filter(EmailLog.created_at >= start, EmailLog.created_at < end).count(),
        })
    return rows


def rebuild_daily_analytics():
    today = datetime.now(timezone.utc).date()
    existing = EmailCampaignAnalytics.query.filter_by(metric_date=today).first()
    if not existing:
        existing = EmailCampaignAnalytics(metric_date=today)
        db.session.add(existing)
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    logs = EmailLog.query.filter(EmailLog.created_at >= start).all()
    existing.sent = sum(1 for log in logs if log.status in ("sent", "delivered"))
    existing.delivered = sum(1 for log in logs if log.status == "delivered")
    existing.failed = sum(1 for log in logs if log.status == "failed")
    existing.bounced = sum(1 for log in logs if log.bounced_at)
    existing.opened = sum(1 for log in logs if log.opened_at)
    existing.clicked = sum(1 for log in logs if log.clicked_at)
    db.session.commit()


def export_logs_csv(query):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "User ID", "Email", "Subject", "Status", "Sent At", "Opened", "Clicked", "Failed Reason", "Resend Message ID"])
    for log in query:
        writer.writerow([
            log.id, log.user_id or "", log.to_email, log.subject, log.status,
            log.sent_at.isoformat() if log.sent_at else "",
            log.opened_at.isoformat() if log.opened_at else "",
            log.clicked_at.isoformat() if log.clicked_at else "",
            log.failed_reason or "", log.provider_message_id or "",
        ])
    return output.getvalue()


def seed_email_center():
    defaults = [
        ("email-verification", "Email Verification", "transactional", "Verify Your Email - Tragene Funded", """
        <div style="font-family:Arial,sans-serif;padding:24px;color:#111827">
          <h2>Verify your email</h2>
          <p>Hello {{name}},</p>
          <p>Confirm your email address to continue your {{company_name}} account setup.</p>
          <p><a href="{{verification_link}}" style="background:#16a34a;color:white;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">Verify Email</a></p>
          <p style="font-size:12px;color:#6b7280">If you did not create this account, you can ignore this email.</p>
        </div>""", ["name", "verification_link", "company_name"]),
        ("welcome-email", "Welcome Email", "transactional", "Welcome to Tragene Funded", "<p>Hello {{name}}, welcome to {{company_name}}. Your account is ready.</p>", ["name", "company_name"]),
        ("kyc-approved", "KYC Approved", "kyc", "KYC Approved - Tragene Funded", "<p>Hello {{name}}, your KYC has been approved. You can now purchase challenges.</p>", ["name"]),
        ("purchase-confirmation", "Purchase Confirmation", "transactional", "Challenge Purchase Confirmed", "<p>Hello {{name}}, your {{challenge}} purchase is confirmed. Order: {{order_id}}</p>", ["name", "challenge", "order_id"]),
        ("challenge-passed", "Challenge Passed", "challenge", "Challenge Passed - Tragene Funded", "<p>Congratulations {{name}}, you passed {{challenge}}.</p>", ["name", "challenge"]),
        ("challenge-failed", "Challenge Failed", "challenge", "Challenge Failed - Tragene Funded", "<p>Hello {{name}}, your {{challenge}} has been marked failed. You can review available evidence here: {{evidence_url}}</p>", ["name", "challenge", "evidence_url"]),
        ("password-reset", "Password Reset", "transactional", "Reset Your Password - Tragene Funded", """
        <div style="font-family:Arial,sans-serif;padding:24px;color:#111827">
          <h2>Reset your password</h2>
          <p>Hello {{name}},</p>
          <p>Use the button below to choose a new password. This link expires in 1 hour.</p>
          <p><a href="{{reset_link}}" style="background:#2563eb;color:white;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">Reset Password</a></p>
          <p style="font-size:12px;color:#6b7280">If you did not request this, you can ignore this email.</p>
        </div>""", ["name", "reset_link"]),
    ]
    for slug, name, category, subject, html, variables in defaults:
        template = EmailTemplate.query.filter_by(slug=slug).first()
        if not template:
            db.session.add(EmailTemplate(
                slug=slug,
                name=name,
                category=category,
                subject=subject,
                html_body=html.strip(),
                variables=variables,
                is_active=True,
            ))
    db.session.flush()

    automations = [
        ("email_verification", "Email Verification", "registration", "email-verification", "none", True),
        ("welcome_email", "Welcome Email", "email_verified", "welcome-email", "user", False),
        ("kyc_approved", "KYC Approved", "kyc_approved", "kyc-approved", "user", False),
        ("purchase_confirmation", "Purchase Confirmation", "payment_success", "purchase-confirmation", "none", False),
        ("challenge_passed", "Challenge Passed", "challenge_passed", "challenge-passed", "challenge", False),
        ("challenge_failed", "Challenge Failed", "challenge_failed", "challenge-failed", "challenge", False),
    ]
    for key, name, event, template_slug, scope, system in automations:
        template = EmailTemplate.query.filter_by(slug=template_slug).first()
        rule = EmailAutomationRule.query.filter_by(key=key).first()
        if not rule:
            db.session.add(EmailAutomationRule(
                key=key,
                name=name,
                event=event,
                template_id=template.id if template else None,
                once_scope=scope,
                is_system=system,
                is_enabled=True,
            ))
    db.session.commit()
