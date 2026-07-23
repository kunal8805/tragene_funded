from datetime import datetime, timezone, timedelta

from models import db, Notification, UserNotification


VALID_NOTIFICATION_TYPES = {
    'welcome',
    'kyc',
    'challenge',
    'coupon',
    'payout',
    'system',
    'promotion',
}


def create_notification(
    user_id,
    title,
    message,
    notification_type,
    action_url=None,
    icon=None,
    admin_id=None,
    dedupe_key=None,
    expires_in_days=30,
):
    notification_type = notification_type if notification_type in VALID_NOTIFICATION_TYPES else 'system'
    is_global = user_id is None
    expires_at = None
    if expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    existing = None
    if dedupe_key:
        query = Notification.query.filter_by(
            dedupe_key=dedupe_key,
            is_global=is_global,
            target_user_id=user_id,
            is_deleted=False,
        )
        existing = query.first()

    if existing:
        if user_id is not None:
            mapping = UserNotification.query.filter_by(
                notification_id=existing.id,
                user_id=user_id,
            ).first()
            if not mapping:
                db.session.add(UserNotification(notification_id=existing.id, user_id=user_id))
        return existing

    # FIX: Validate admin_id - if it's a moderator ID, find the super admin
    safe_admin_id = None
    if admin_id:
        from models import User
        admin_user = User.query.get(admin_id)
        if admin_user and admin_user.is_admin:
            safe_admin_id = admin_id
        else:
            # It's a moderator ID or invalid - fall back to first super admin
            super_admin = User.query.filter_by(is_admin=True).first()
            safe_admin_id = super_admin.id if super_admin else None
    else:
        # No admin_id provided - use first super admin
        super_admin = User.query.filter_by(is_admin=True).first()
        safe_admin_id = super_admin.id if super_admin else None

    notification = Notification(
        title=title,
        message=message,
        notification_type=notification_type,
        action_url=action_url,
        icon=icon,
        dedupe_key=dedupe_key,
        is_global=is_global,
        target_user_id=user_id,
        created_by_admin_id=safe_admin_id,
        expires_at=expires_at,
    )
    db.session.add(notification)
    db.session.flush()

    if user_id is not None:
        db.session.add(UserNotification(notification_id=notification.id, user_id=user_id))

    return notification


def notify_all_users(
    title,
    message,
    notification_type,
    action_url=None,
    icon=None,
    admin_id=None,
    dedupe_key=None,
    expires_in_days=30,
):
    return create_notification(
        None,
        title,
        message,
        notification_type,
        action_url=action_url,
        icon=icon,
        admin_id=admin_id,
        dedupe_key=dedupe_key,
        expires_in_days=expires_in_days,
    )