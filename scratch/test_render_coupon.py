from app import app
from flask import render_template
from datetime import datetime, timezone

# We need a request context to use render_template
with app.test_request_context():
    # Let's create a mockup coupon class
    class MockCoupon:
        id = 1
        code = "TEST50"
        coupon_type = "universal"
        discount_type = "percent"
        discount_value = 50.0
        used_count = 5
        max_uses = 10
        expires_at = datetime.now(timezone.utc)
        is_active = True

    try:
        # Try to render the admin coupons template
        rendered = render_template('admin/coupons.html', coupons=[MockCoupon()])
        print("[SUCCESS] Template rendered successfully!")
        print(f"Contains 'Expired': {'Expired' in rendered}")
    except Exception as e:
        print(f"[ERROR] Failed to render template: {e}")
        import traceback
        traceback.print_exc()
