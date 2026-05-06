"""
Challenge Authentication Helper Functions

Provides secure generation of:
- serial_no: Sequential tracking number starting from 1111
- challenge_code: 6-digit numeric EA identifier
- challenge_token: Cryptographically secure authentication token
"""
import secrets
import random
from models import db, ChallengePurchase


def get_next_serial_no():
    """
    Get next sequential serial number starting from 1111.
    
    Returns:
        int: Next available serial number
    """
    max_serial = db.session.query(db.func.max(ChallengePurchase.serial_no)).scalar()
    
    if max_serial is None:
        return 1111
    
    return max_serial + 1


def generate_challenge_code():
    """
    Generate random 6-digit numeric challenge code.
    
    Returns:
        str: 6-digit numeric string (e.g., "483921")
    """
    while True:
        # Generate random 6-digit number
        code = str(random.randint(100000, 999999))
        
        # Check if code already exists
        existing = ChallengePurchase.query.filter_by(challenge_code=code).first()
        if not existing:
            return code


def generate_challenge_token():
    """
    Generate cryptographically secure random token.
    
    Returns:
        str: 64-character hexadecimal token
    """
    while True:
        # Generate 32 random bytes = 64 hex characters
        token = secrets.token_hex(32)
        
        # Check if token already exists (extremely unlikely but safe)
        existing = ChallengePurchase.query.filter_by(challenge_token=token).first()
        if not existing:
            return token
