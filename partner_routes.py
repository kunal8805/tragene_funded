from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for
from functools import wraps
from models import db, User, PartnerEarnings, ChallengeTemplate
from sqlalchemy import func

partner_bp = Blueprint('partner', __name__, url_prefix='/partner')

def partner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'error')
            return redirect(url_for('auth.login'))
        
        user = User.query.get(session['user_id'])
        if not user or user.role != 'partner':
            flash('Access denied. Partner privileges required.', 'error')
            return redirect(url_for('user.dashboard'))
            
        if user.is_banned:
            flash('Your access has been revoked.', 'error')
            return redirect(url_for('auth.logout'))
            
        return f(*args, **kwargs)
    return decorated

@partner_bp.route('/dashboard', methods=['GET'])
@partner_required
def dashboard():
    user = User.query.get(session['user_id'])
    
    # Calculate summary metrics
    total_earned = db.session.query(func.sum(PartnerEarnings.partner_share)).filter_by(partner_id=user.id).scalar() or 0.0
    total_sales = PartnerEarnings.query.filter_by(partner_id=user.id).count()
    
    # Get recent earnings
    recent_earnings = PartnerEarnings.query.filter_by(partner_id=user.id).order_by(PartnerEarnings.purchased_at.desc()).limit(10).all()
    
    return render_template('partner/dashboard.html', 
                           user=user, 
                           total_earned=total_earned, 
                           total_sales=total_sales,
                           recent_earnings=recent_earnings)

@partner_bp.route('/api/challenges', methods=['GET'])
@partner_required
def partner_challenges():
    user_id = session['user_id']
    earnings = PartnerEarnings.query.filter_by(partner_id=user_id).order_by(PartnerEarnings.purchased_at.desc()).all()
    
    result = []
    for e in earnings:
        result.append({
            "challenge_name": e.challenge.name if e.challenge else "Unknown Challenge",
            "buyer": f"{e.user.first_name} {e.user.last_name}" if e.user else "Unknown User",
            "purchase_amount": e.purchase_amount,
            "your_share": e.partner_share,
            "date": e.purchased_at.isoformat() if e.purchased_at else None
        })
        
    return jsonify(result)

@partner_bp.route('/api/summary', methods=['GET'])
@partner_required
def partner_summary():
    user_id = session['user_id']
    total_earned = db.session.query(func.sum(PartnerEarnings.partner_share)).filter_by(partner_id=user_id).scalar() or 0.0
    total_sales = PartnerEarnings.query.filter_by(partner_id=user_id).count()
    
    return jsonify({
        "total_challenges_sold": total_sales,
        "total_earned": total_earned
    })
