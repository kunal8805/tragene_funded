import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app
import models
from datetime import datetime, timedelta, timezone, date

def run_tests():
    print("=== STARTING COUPON AUTOMATED TESTS ===")
    ctx = app.app.app_context()
    ctx.push()
    
    # 1. Setup clean test data
    # Create a test user
    test_user_email = "coupon_test_user@example.com"
    user = models.User.query.filter_by(email=test_user_email).first()
    if not user:
        user = models.User(
            first_name="Coupon",
            last_name="TestUser",
            email=test_user_email,
            phone="1234567890",
            dob=date(1990, 1, 1),
            country="India",
            kyc_status="approved",
            is_admin=False
        )
        user.set_password("password123")
        models.db.session.add(user)
    else:
        # Reset state if user already existed
        user.kyc_status = "approved"
    
    # Create an admin user to act as creator
    admin_email = "coupon_test_admin@example.com"
    admin = models.User.query.filter_by(email=admin_email).first()
    if not admin:
        admin = models.User(
            first_name="Coupon",
            last_name="TestAdmin",
            email=admin_email,
            phone="0987654321",
            dob=date(1985, 1, 1),
            country="India",
            kyc_status="approved",
            is_admin=True
        )
        admin.set_password("password123")
        models.db.session.add(admin)
        
    models.db.session.commit()

    # Clean existing test coupons to avoid duplication/clashes
    test_codes = ["TESTPERCENT", "TESTFIXED", "TESTEXPIRED", "TESTMAXUSES", "TESTSPECIFIC", "TESTCAP"]
    for code in test_codes:
        models.Coupon.query.filter_by(code=code).delete()
    models.db.session.commit()

    # 2. Test 1: Percent Discount Validation
    coupon_percent = models.Coupon(
        code="TESTPERCENT",
        description="20% off coupon",
        coupon_type="universal",
        discount_type="percent",
        discount_value=20.0,
        max_uses=10,
        is_active=True,
        created_by_admin_id=admin.id
    )
    models.db.session.add(coupon_percent)
    models.db.session.commit()
    
    is_valid, msg, discount, final = coupon_percent.validate_for_user_and_price(user.id, 100.0)
    assert is_valid == True, f"Percent validation failed: {msg}"
    assert discount == 20.0, f"Percent discount mismatch: expected 20.0, got {discount}"
    assert final == 80.0, f"Percent final price mismatch: expected 80.0, got {final}"
    print("[OK] Test 1: Percent discount math validated successfully.")

    # 3. Test 2: Fixed Discount Validation
    coupon_fixed = models.Coupon(
        code="TESTFIXED",
        description="INR 50 off coupon",
        coupon_type="universal",
        discount_type="fixed",
        discount_value=50.0,
        max_uses=10,
        is_active=True,
        created_by_admin_id=admin.id
    )
    models.db.session.add(coupon_fixed)
    models.db.session.commit()
    
    is_valid, msg, discount, final = coupon_fixed.validate_for_user_and_price(user.id, 150.0)
    assert is_valid == True, f"Fixed validation failed: {msg}"
    assert discount == 50.0, f"Fixed discount mismatch: expected 50.0, got {discount}"
    assert final == 100.0, f"Fixed final price mismatch: expected 100.0, got {final}"
    print("[OK] Test 2: Fixed discount math validated successfully.")

    # 4. Test 3: Expired Coupon
    coupon_expired = models.Coupon(
        code="TESTEXPIRED",
        description="Expired coupon",
        coupon_type="universal",
        discount_type="percent",
        discount_value=10.0,
        max_uses=10,
        is_active=True,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        created_by_admin_id=admin.id
    )
    models.db.session.add(coupon_expired)
    models.db.session.commit()
    
    is_valid, msg, discount, final = coupon_expired.validate_for_user_and_price(user.id, 100.0)
    assert is_valid == False, "Expired coupon should be invalid"
    assert "expired" in msg.lower(), f"Unexpected message: {msg}"
    print("[OK] Test 3: Expired coupon check validated successfully.")

    # 5. Test 4: Max Uses Exceeded
    coupon_max = models.Coupon(
        code="TESTMAXUSES",
        description="Max uses coupon",
        coupon_type="universal",
        discount_type="percent",
        discount_value=10.0,
        max_uses=2,
        used_count=2,
        is_active=True,
        created_by_admin_id=admin.id
    )
    models.db.session.add(coupon_max)
    models.db.session.commit()
    
    is_valid, msg, discount, final = coupon_max.validate_for_user_and_price(user.id, 100.0)
    assert is_valid == False, "Coupon with exceeded max uses should be invalid"
    assert "limit" in msg.lower(), f"Unexpected message: {msg}"
    print("[OK] Test 4: Max uses check validated successfully.")

    # 6. Test 5: Specific User Assignment
    coupon_spec = models.Coupon(
        code="TESTSPECIFIC",
        description="Specific user coupon",
        coupon_type="specific",
        discount_type="percent",
        discount_value=15.0,
        is_active=True,
        created_by_admin_id=admin.id
    )
    models.db.session.add(coupon_spec)
    models.db.session.flush() # get id
    
    # Create another user without assignment (or retrieve if existing)
    other_user = models.User.query.filter_by(email="other_coupon_test@example.com").first()
    if not other_user:
        other_user = models.User(
            first_name="Other",
            last_name="User",
            email="other_coupon_test@example.com",
            phone="5555555555",
            dob=date(1995, 1, 1),
            country="India"
        )
        other_user.set_password("password123")
        models.db.session.add(other_user)
        models.db.session.flush()
    
    models.db.session.commit()
    
    # Try validating for other user (should fail)
    is_valid, msg, discount, final = coupon_spec.validate_for_user_and_price(other_user.id, 100.0)
    assert is_valid == False, "Specific coupon should not be valid for unassigned users"
    assert "not assigned" in msg.lower(), f"Unexpected message: {msg}"
    
    # Assign to our user
    assignment = models.CouponAssignment(coupon_id=coupon_spec.id, user_id=user.id)
    models.db.session.add(assignment)
    models.db.session.commit()
    
    # Validate for assigned user (should succeed)
    is_valid, msg, discount, final = coupon_spec.validate_for_user_and_price(user.id, 100.0)
    assert is_valid == True, f"Specific validation failed for assigned user: {msg}"
    assert discount == 15.0, f"Discount mismatched: {discount}"
    print("[OK] Test 5: Specific user assignment checks validated successfully.")

    # 7. Test 6: Capping Discount at INR 1 minimum final price
    coupon_cap = models.Coupon(
        code="TESTCAP",
        description="Cap coupon",
        coupon_type="universal",
        discount_type="fixed",
        discount_value=120.0,
        is_active=True,
        created_by_admin_id=admin.id
    )
    models.db.session.add(coupon_cap)
    models.db.session.commit()
    
    is_valid, msg, discount, final = coupon_cap.validate_for_user_and_price(user.id, 100.0)
    assert is_valid == True, f"Cap validation failed: {msg}"
    assert final == 1.0, f"Final price should be capped at INR 1.0, got: {final}"
    assert discount == 99.0, f"Discount amount should be capped at INR 99.0, got: {discount}"
    print("[OK] Test 6: Price capping at INR 1 minimum final price validated successfully.")

    # Clean up test database mutations
    for code in test_codes:
        models.Coupon.query.filter_by(code=code).delete()
    
    # Safely delete created users
    models.User.query.filter(models.User.email.in_([test_user_email, admin_email, "other_coupon_test@example.com"])).delete(synchronize_session='fetch')
    models.db.session.commit()
    print("=== ALL COUPON TESTS COMPLETED SUCCESSFULLY ===")

if __name__ == '__main__':
    run_tests()
