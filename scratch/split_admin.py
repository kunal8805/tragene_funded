import re
import os

source_file = 'c:/codes/tragene funded/admin_routes.py.bak'
output_dir = 'c:/codes/tragene funded/admin_routes'

with open(source_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Categorize the functions
categories = {
    'admin_users': [
        'admin_users', 'admin_kyc', 'admin_kyc_review', 'admin_approve_kyc', 'admin_reject_kyc', 
        'admin_delete_kyc', 'admin_bulk_kyc_action', 'admin_ban_user', 'admin_unban_user', 
        'admin_verify_phone', 'admin_bulk_action', 'api_users', 'admin_user_detail', 
        'admin_reset_user_password', 'admin_delete_user', 'admin_user_analytics', 
        'ban_partner', 'unban_partner', 'revoke_partner', 'partners', 'create_partner', 
        'partner_earnings', 'toggle_hide_earning', 'leads', 'lead_detail', 'leads_api_stats', 
        'leads_api_statuses', 'leads_api_create_status', 'leads_api_edit_status', 
        'leads_api_delete_status', 'leads_api_list', 'leads_api_change_status', 'leads_api_notes', 
        'leads_api_delete_note', 'leads_api_followups', 'leads_api_complete_followup', 'leads_api_bulk_action'
    ],
    'admin_challenges': [
        'admin_search_challenges', 'admin_challenge_action', 'admin_bulk_challenge_action', 
        'admin_challenge_details', 'admin_challenge_templates', 'admin_challenge_purchases', 
        'admin_manage_challenges', 'admin_save_challenge', 'admin_edit_challenge', 
        'admin_delete_challenge', 'admin_toggle_challenge', 'admin_progression_requests', 
        'admin_progression_request_action', 'admin_challenges', 'admin_challenge_detail', 
        'api_user_challenges_metrics', 'api_user_calendar', 'api_all_challenges', 
        'api_challenge_details', 'api_challenge_violations', 'api_clear_flag', 
        'api_challenge_action', 'admin_violations', 'admin_violation_detail', 
        'admin_violation_action', 'api_violation_detail', 'api_challenge_violations_list',
        'admin_palantir', 'api_palantir', 'api_palantir_activity'
    ],
    'admin_finance': [
        'admin_payments', 'admin_api_payments', 'admin_mark_refund', 'refund_payment', 
        'update_payment_status', 'export_payments', 'admin_payouts', 'admin_payout_history', 
        'export_payouts', 'admin_payout_action', 'admin_coupons', 'admin_coupon_detail', 
        'admin_delete_coupon', 'admin_coupon_analytics', 'admin_affiliate_rewards', 
        'update_affiliate_settings', 'moderate_affiliate', 'adjust_wallet', 
        'update_wallet_withdrawal', 'admin_analytics'
    ],
    'admin_engagement': [
        'admin_rulebook', 'admin_rulebook_save', 'admin_rulebook_toggle', 'admin_rulebook_delete', 
        'admin_rulebook_reorder', 'admin_faq', 'admin_faq_create', 'admin_faq_edit', 'admin_faq_delete', 
        'admin_support', 'admin_ticket_detail', 'admin_ticket_reply', 'admin_ticket_status', 
        'admin_ticket_note', 'admin_notifications', 'admin_delete_notification', 'admin_surveys', 
        'assign_survey', 'grant_call_survey_reward', 'admin_settings'
    ],
    '__init__': [
        'admin_dashboard', 'admin_404'
    ]
}

# The header goes up to the first @admin_bp.route or @admin_bp.errorhandler
first_route_idx = min(
    content.find('@admin_bp.route'),
    content.find('@admin_bp.errorhandler')
)
header = content[:first_route_idx]
rest_of_content = content[first_route_idx:]

# Split the rest into individual blocks
# A block starts with @admin_bp.
# We can use a regex to find all start indices
pattern = re.compile(r'^@admin_bp\.(?:route|errorhandler)', re.MULTILINE)
matches = [m.start() for m in pattern.finditer(rest_of_content)]
blocks = []
for i in range(len(matches)):
    start = matches[i]
    end = matches[i+1] if i + 1 < len(matches) else len(rest_of_content)
    blocks.append(rest_of_content[start:end])

# Function to get the function name from a block
def get_func_name(block):
    match = re.search(r'def ([a-zA-Z0-9_]+)\(', block)
    return match.group(1) if match else None

# Prepare file contents
file_contents = {
    'admin_users': [],
    'admin_challenges': [],
    'admin_finance': [],
    'admin_engagement': [],
    '__init__': []
}

for block in blocks:
    func_name = get_func_name(block)
    if not func_name:
        file_contents['__init__'].append(block)
        continue
    
    found = False
    for category, funcs in categories.items():
        if func_name in funcs:
            file_contents[category].append(block)
            found = True
            break
            
    if not found:
        # Default fallback
        file_contents['__init__'].append(block)

# Common imports for the 4 module files
common_imports = """from flask import render_template, request, redirect, url_for, flash, session, jsonify, abort, Response, send_file
from datetime import datetime, timedelta, timezone
from models import db, User, ChallengeTemplate, ChallengePurchase, Payout, PayoutAuditLog, FAQ, SupportTicket, TicketMessage, Payment, AdminLog, Notification, UserNotification, NotificationTemplate, Coupon, CouponUsage, CouponAssignment, ProgressionRequest, RulebookSection
from . import admin_bp, admin_required
import secrets
import csv
import io
import json
"""

# Write files
os.makedirs(output_dir, exist_ok=True)

# Write __init__.py
with open(os.path.join(output_dir, '__init__.py'), 'w', encoding='utf-8') as f:
    f.write(header)
    f.write('\n\n')
    for block in file_contents['__init__']:
        f.write(block)
        f.write('\n')
    
    f.write('\n# Import routes to register them with admin_bp\n')
    f.write('from . import admin_users\n')
    f.write('from . import admin_challenges\n')
    f.write('from . import admin_finance\n')
    f.write('from . import admin_engagement\n')

# Write the 4 domain files
for filename in ['admin_users', 'admin_challenges', 'admin_finance', 'admin_engagement']:
    with open(os.path.join(output_dir, f'{filename}.py'), 'w', encoding='utf-8') as f:
        f.write(common_imports)
        f.write('\n')
        # Some helper imports from __init__ might be needed, so just import everything from . for safety?
        f.write(f"from . import _admin_name, _notify_user, _notify_challenge_passed, _notify_challenge_breached, _activate_progression_stage, _payout_audit, _eligible_funded_count, _payout_stats\n\n")
        
        for block in file_contents[filename]:
            f.write(block)
            f.write('\n')

print("Successfully split admin_routes.py into modules!")
