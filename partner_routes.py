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
    from datetime import datetime
    user = User.query.get(session['user_id'])
    
    # Calculate summary metrics (excluding hidden)
    total_earned = db.session.query(func.sum(PartnerEarnings.partner_share)).filter(
        PartnerEarnings.partner_id == user.id,
        (PartnerEarnings.is_hidden == False) | (PartnerEarnings.is_hidden == None)
    ).scalar() or 0.0
    
    total_sales = PartnerEarnings.query.filter(
        PartnerEarnings.partner_id == user.id,
        (PartnerEarnings.is_hidden == False) | (PartnerEarnings.is_hidden == None)
    ).count()
    
    # Get recent earnings
    query = PartnerEarnings.query.filter(
        PartnerEarnings.partner_id == user.id,
        (PartnerEarnings.is_hidden == False) | (PartnerEarnings.is_hidden == None)
    )
    
    start_date_str = request.args.get('start_date')
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(PartnerEarnings.purchased_at >= start_date)
        except ValueError:
            pass
            
    recent_earnings = query.order_by(PartnerEarnings.purchased_at.desc()).limit(10).all()
    
    return render_template('partner/dashboard.html', 
                           user=user, 
                           total_earned=total_earned, 
                           total_sales=total_sales,
                           recent_earnings=recent_earnings,
                           start_date=start_date_str)

@partner_bp.route('/api/challenges', methods=['GET'])
@partner_required
def partner_challenges():
    user_id = session['user_id']
    earnings = PartnerEarnings.query.filter(
        PartnerEarnings.partner_id == user_id,
        (PartnerEarnings.is_hidden == False) | (PartnerEarnings.is_hidden == None)
    ).order_by(PartnerEarnings.purchased_at.desc()).all()
    
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
    total_earned = db.session.query(func.sum(PartnerEarnings.partner_share)).filter(
        PartnerEarnings.partner_id == user_id,
        (PartnerEarnings.is_hidden == False) | (PartnerEarnings.is_hidden == None)
    ).scalar() or 0.0
    
    total_sales = PartnerEarnings.query.filter(
        PartnerEarnings.partner_id == user_id,
        (PartnerEarnings.is_hidden == False) | (PartnerEarnings.is_hidden == None)
    ).count()
    
    return jsonify({
        "total_challenges_sold": total_sales,
        "total_earned": total_earned
    })
