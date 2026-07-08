from datetime import datetime, timedelta, timezone

from flask import Response, flash, jsonify, redirect, render_template, request, session, url_for

from models import (
    db,
    User,
    EmailAutomationRule,
    EmailCampaign,
    EmailLog,
    EmailPreference,
    EmailTemplate,
    ScheduledEmail,
)
from email_service import (
    AUDIENCE_TYPES,
    CAMPAIGN_TYPES,
    TEMPLATE_CATEGORIES,
    chart_counts,
    export_logs_csv,
    get_or_create_preferences,
    resolve_audience,
    seed_email_center,
    send_campaign,
    send_email,
    stats_snapshot,
)
from . import admin_bp, admin_required


def _json_field(name):
    value = request.form.get(name, "").strip()
    if not value:
        return {}
    if name == "variables":
        return [x.strip() for x in value.split(",") if x.strip()]
    if name in ("emails", "user_ids"):
        return [x.strip() for x in value.split(",") if x.strip()]
    return value


def _template_form(template=None):
    template = template or EmailTemplate()
    template.name = request.form.get("name", "").strip()
    template.slug = request.form.get("slug", "").strip().lower().replace(" ", "-")
    template.category = request.form.get("category", "transactional")
    template.subject = request.form.get("subject", "").strip()
    template.html_body = request.form.get("html_body", "").strip()
    template.text_body = request.form.get("text_body", "").strip()
    template.variables = _json_field("variables")
    template.is_active = request.form.get("is_active") == "on"
    if not template.slug:
        template.slug = template.name.lower().replace(" ", "-")
    template.updated_by = session.get("user_id")
    if not template.id:
        template.created_by = session.get("user_id")
    return template


@admin_bp.route("/email-center")
@admin_required
def email_center_dashboard():
    seed_email_center()
    stats = stats_snapshot()
    recent_logs = EmailLog.query.order_by(EmailLog.created_at.desc()).limit(12).all()
    top_templates = db.session.query(
        EmailTemplate.name,
        db.func.count(EmailLog.id).label("total")
    ).join(EmailLog, EmailLog.template_id == EmailTemplate.id).group_by(EmailTemplate.id).order_by(db.desc("total")).limit(8).all()
    top_types = db.session.query(
        EmailTemplate.category,
        db.func.count(EmailLog.id).label("total")
    ).join(EmailLog, EmailLog.template_id == EmailTemplate.id).group_by(EmailTemplate.category).order_by(db.desc("total")).limit(8).all()
    return render_template(
        "admin/email/dashboard.html",
        stats=stats,
        daily=chart_counts(30),
        recent_logs=recent_logs,
        top_templates=top_templates,
        top_types=top_types,
    )


@admin_bp.route("/email-center/templates", methods=["GET", "POST"])
@admin_required
def email_templates():
    seed_email_center()
    if request.method == "POST":
        template = _template_form()
        if not template.name or not template.subject or not template.html_body:
            flash("Name, subject and HTML are required.", "error")
        elif EmailTemplate.query.filter_by(slug=template.slug).first():
            flash("Template slug already exists.", "error")
        else:
            db.session.add(template)
            db.session.commit()
            flash("Email template created.", "success")
        return redirect(url_for("admin.email_templates"))

    templates = EmailTemplate.query.order_by(EmailTemplate.created_at.desc()).all()
    return render_template("admin/email/templates.html", templates=templates, categories=TEMPLATE_CATEGORIES, edit_template=None)


@admin_bp.route("/email-center/templates/<int:template_id>", methods=["GET", "POST"])
@admin_required
def email_template_edit(template_id):
    template = EmailTemplate.query.get_or_404(template_id)
    if request.method == "POST":
        old_slug = template.slug
        template = _template_form(template)
        duplicate = EmailTemplate.query.filter(EmailTemplate.slug == template.slug, EmailTemplate.id != template.id).first()
        if duplicate:
            template.slug = old_slug
            flash("Template slug already exists.", "error")
        else:
            db.session.commit()
            flash("Email template updated.", "success")
        return redirect(url_for("admin.email_template_edit", template_id=template.id))
    templates = EmailTemplate.query.order_by(EmailTemplate.created_at.desc()).all()
    return render_template("admin/email/templates.html", templates=templates, categories=TEMPLATE_CATEGORIES, edit_template=template)


@admin_bp.route("/email-center/templates/<int:template_id>/<action>", methods=["POST"])
@admin_required
def email_template_action(template_id, action):
    template = EmailTemplate.query.get_or_404(template_id)
    if action == "duplicate":
        copy = EmailTemplate(
            name=f"{template.name} Copy",
            slug=f"{template.slug}-copy-{int(datetime.now().timestamp())}",
            category=template.category,
            subject=template.subject,
            html_body=template.html_body,
            text_body=template.text_body,
            variables=template.variables,
            created_by=session.get("user_id"),
        )
        db.session.add(copy)
        flash("Template duplicated.", "success")
    elif action == "toggle":
        template.is_active = not template.is_active
        flash("Template status updated.", "success")
    elif action == "delete":
        db.session.delete(template)
        flash("Template deleted.", "success")
    db.session.commit()
    return redirect(url_for("admin.email_templates"))


@admin_bp.route("/email-center/templates/<int:template_id>/test", methods=["POST"])
@admin_required
def email_template_test(template_id):
    template = EmailTemplate.query.get_or_404(template_id)
    to_email = request.form.get("test_email", "").strip()
    admin_user = User.query.get(session.get("user_id"))
    if not to_email:
        to_email = admin_user.email
    send_email(to_email, template.subject, template.html_body, user=admin_user, template=template, ignore_preferences=True)
    flash(f"Test email queued for {to_email}.", "success")
    return redirect(url_for("admin.email_template_edit", template_id=template.id))


@admin_bp.route("/email-center/automations", methods=["GET", "POST"])
@admin_required
def email_automations():
    seed_email_center()
    if request.method == "POST":
        rule = EmailAutomationRule.query.get_or_404(request.form.get("rule_id", type=int))
        rule.subject_override = request.form.get("subject_override", "").strip() or None
        rule.html_override = request.form.get("html_override", "").strip() or None
        rule.template_id = request.form.get("template_id", type=int) or rule.template_id
        rule.is_enabled = request.form.get("is_enabled") == "on"
        rule.is_paused = request.form.get("is_paused") == "on"
        rule.once_scope = request.form.get("once_scope", rule.once_scope)
        db.session.commit()
        flash("Automation updated.", "success")
        return redirect(url_for("admin.email_automations"))
    rules = EmailAutomationRule.query.order_by(EmailAutomationRule.name).all()
    templates = EmailTemplate.query.filter_by(is_active=True).order_by(EmailTemplate.name).all()
    return render_template("admin/email/automations.html", rules=rules, templates=templates)


@admin_bp.route("/email-center/automations/<int:rule_id>/<action>", methods=["POST"])
@admin_required
def email_automation_action(rule_id, action):
    rule = EmailAutomationRule.query.get_or_404(rule_id)
    if action == "duplicate":
        copy = EmailAutomationRule(
            key=f"{rule.key}_copy_{int(datetime.now().timestamp())}",
            name=f"{rule.name} Copy",
            event=rule.event,
            template_id=rule.template_id,
            subject_override=rule.subject_override,
            html_override=rule.html_override,
            once_scope=rule.once_scope,
        )
        db.session.add(copy)
        flash("Automation duplicated.", "success")
    elif action == "delete" and not rule.is_system:
        db.session.delete(rule)
        flash("Automation deleted.", "success")
    elif action == "pause":
        rule.is_paused = True
        flash("Automation paused.", "success")
    elif action == "resume":
        rule.is_paused = False
        flash("Automation resumed.", "success")
    elif action == "toggle":
        rule.is_enabled = not rule.is_enabled
        flash("Automation status updated.", "success")
    db.session.commit()
    return redirect(url_for("admin.email_automations"))


@admin_bp.route("/email-center/automations/<int:rule_id>/test", methods=["POST"])
@admin_required
def email_automation_test(rule_id):
    rule = EmailAutomationRule.query.get_or_404(rule_id)
    admin_user = User.query.get(session.get("user_id"))
    template = rule.template
    subject = rule.subject_override or (template.subject if template else "Automation Test")
    html = rule.html_override or (template.html_body if template else "<p>Automation test</p>")
    send_email(admin_user.email, subject, html, user=admin_user, template=template, automation=rule, ignore_preferences=True)
    flash("Automation test email sent.", "success")
    return redirect(url_for("admin.email_automations"))


@admin_bp.route("/email-center/campaigns", methods=["GET", "POST"])
@admin_required
def email_campaigns():
    seed_email_center()
    if request.method == "POST":
        schedule = request.form.get("scheduled_at")
        scheduled_at = datetime.fromisoformat(schedule) if schedule else None
        audience_filters = {
            "user_id": request.form.get("user_id", "").strip(),
            "email": request.form.get("email", "").strip(),
            "emails": request.form.get("emails", "").strip(),
            "user_ids": request.form.get("user_ids", "").strip(),
        }
        campaign = EmailCampaign(
            name=request.form.get("name", "").strip(),
            campaign_type=request.form.get("campaign_type", "general"),
            subject=request.form.get("subject", "").strip(),
            template_id=request.form.get("template_id", type=int),
            audience_type=request.form.get("audience_type", "all_users"),
            audience_filters=audience_filters,
            status=request.form.get("status", "draft"),
            scheduled_at=scheduled_at,
            recurring_rule=request.form.get("recurring_rule") or None,
            created_by=session.get("user_id"),
        )
        if request.form.get("send_now") == "on":
            campaign.status = "sending"
        db.session.add(campaign)
        db.session.commit()
        if request.form.get("send_now") == "on":
            count = send_campaign(campaign)
            flash(f"Campaign sent to {count} recipient(s).", "success")
        else:
            flash("Campaign saved.", "success")
        return redirect(url_for("admin.email_campaigns"))

    campaigns = EmailCampaign.query.order_by(EmailCampaign.created_at.desc()).all()
    templates = EmailTemplate.query.filter_by(is_active=True).order_by(EmailTemplate.name).all()
    return render_template("admin/email/campaigns.html", campaigns=campaigns, templates=templates, campaign_types=CAMPAIGN_TYPES, audience_types=AUDIENCE_TYPES)


@admin_bp.route("/email-center/campaigns/<int:campaign_id>/<action>", methods=["POST"])
@admin_required
def email_campaign_action(campaign_id, action):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if action == "send":
        count = send_campaign(campaign)
        flash(f"Campaign sent to {count} recipient(s).", "success")
    elif action == "duplicate":
        copy = EmailCampaign(
            name=f"{campaign.name} Copy",
            campaign_type=campaign.campaign_type,
            subject=campaign.subject,
            template_id=campaign.template_id,
            audience_type=campaign.audience_type,
            audience_filters=campaign.audience_filters,
            status="draft",
            created_by=session.get("user_id"),
        )
        db.session.add(copy)
        flash("Campaign duplicated.", "success")
    elif action == "pause":
        campaign.status = "paused"
        flash("Campaign paused.", "success")
    elif action == "resume":
        campaign.status = "scheduled" if campaign.scheduled_at else "draft"
        flash("Campaign resumed.", "success")
    elif action == "archive":
        campaign.status = "archived"
        campaign.archived_at = datetime.now(timezone.utc)
        flash("Campaign archived.", "success")
    elif action == "delete":
        db.session.delete(campaign)
        flash("Campaign deleted.", "success")
    db.session.commit()
    return redirect(url_for("admin.email_campaigns"))


@admin_bp.route("/email-center/audience")
@admin_required
def email_audience():
    audience_type = request.args.get("audience_type", "all_users")
    filters = {
        "user_id": request.args.get("user_id", ""),
        "email": request.args.get("email", ""),
        "emails": request.args.get("emails", ""),
        "user_ids": request.args.get("user_ids", ""),
    }
    users = resolve_audience(audience_type, filters)[:200]
    return render_template("admin/email/audience.html", audience_types=AUDIENCE_TYPES, selected=audience_type, users=users, filters=filters)


@admin_bp.route("/email-center/analytics")
@admin_required
def email_analytics():
    stats = stats_snapshot()
    per_campaign = db.session.query(EmailCampaign.name, db.func.count(EmailLog.id).label("total")).join(EmailLog, EmailLog.campaign_id == EmailCampaign.id).group_by(EmailCampaign.id).order_by(db.desc("total")).limit(20).all()
    per_template = db.session.query(EmailTemplate.name, db.func.count(EmailLog.id).label("total")).join(EmailLog, EmailLog.template_id == EmailTemplate.id).group_by(EmailTemplate.id).order_by(db.desc("total")).limit(20).all()
    per_automation = db.session.query(EmailAutomationRule.name, db.func.count(EmailLog.id).label("total")).join(EmailLog, EmailLog.automation_id == EmailAutomationRule.id).group_by(EmailAutomationRule.id).order_by(db.desc("total")).limit(20).all()
    return render_template("admin/email/analytics.html", stats=stats, daily=chart_counts(60), per_campaign=per_campaign, per_template=per_template, per_automation=per_automation)


@admin_bp.route("/email-center/logs")
@admin_required
def email_logs():
    q = EmailLog.query
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(EmailLog.to_email.ilike(like), EmailLog.subject.ilike(like), EmailLog.provider_message_id.ilike(like)))
    if status:
        q = q.filter_by(status=status)
    if request.args.get("export") == "csv":
        csv_data = export_logs_csv(q.order_by(EmailLog.created_at.desc()).all())
        return Response(csv_data, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=email_logs.csv"})
    logs = q.order_by(EmailLog.created_at.desc()).paginate(page=request.args.get("page", 1, type=int), per_page=50, error_out=False)
    return render_template("admin/email/logs.html", logs=logs, search=search, status=status)


@admin_bp.route("/email-center/logs/delete", methods=["POST"])
@admin_required
def email_logs_delete():
    days = request.form.get("days", type=int) or 90
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = EmailLog.query.filter(EmailLog.created_at < cutoff).delete()
    db.session.commit()
    flash(f"Deleted {deleted} old email log(s).", "success")
    return redirect(url_for("admin.email_logs"))


@admin_bp.route("/email-center/preferences/<int:user_id>", methods=["POST"])
@admin_required
def email_preferences_update(user_id):
    user = User.query.get_or_404(user_id)
    pref = get_or_create_preferences(user.id)
    pref.allow_emails = request.form.get("allow_emails") == "on"
    pref.disable_marketing = request.form.get("disable_marketing") == "on"
    pref.disable_campaigns = request.form.get("disable_campaigns") == "on"
    pref.disable_all = request.form.get("disable_all") == "on"
    pref.admin_override = request.form.get("admin_override") == "on"
    pref.blocked = request.form.get("blocked") == "on"
    pref.blocked_reason = request.form.get("blocked_reason", "")
    pref.notes = request.form.get("notes", "")
    db.session.commit()
    flash("Email preferences updated.", "success")
    return redirect(request.referrer or url_for("admin.admin_user_detail", user_id=user.id))


@admin_bp.route("/users/<int:user_id>/send-email", methods=["POST"])
@admin_required
def email_send_user(user_id):
    user = User.query.get_or_404(user_id)
    template_id = request.form.get("template_id", type=int)
    subject = request.form.get("subject", "").strip()
    message = request.form.get("message", "").strip()
    template = EmailTemplate.query.get(template_id) if template_id else None
    if template:
        subject = subject or template.subject
        message = message or template.html_body
    if not subject or not message:
        flash("Subject and message are required.", "error")
    else:
        send_email(user.email, subject, message, user=user, template=template, ignore_preferences=request.form.get("ignore_preferences") == "on")
        flash(f"Email sent to {user.email}.", "success")
    return redirect(request.referrer or url_for("admin.admin_user_detail", user_id=user.id))
