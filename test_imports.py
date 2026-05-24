import sys
import traceback

def test_imports():
    print("Testing auth_bp...")
    try:
        from auth import auth_bp
        print("Success auth")
    except Exception as e:
        print("Failed auth:")
        traceback.print_exc()

    print("Testing admin_bp...")
    try:
        from admin_routes import admin_bp
        print("Success admin")
    except Exception as e:
        print("Failed admin:")
        traceback.print_exc()

    print("Testing user_bp...")
    try:
        from user_routes import user_bp
        print("Success user")
    except Exception as e:
        print("Failed user:")
        traceback.print_exc()

    print("Testing partner_bp...")
    try:
        from partner_routes import partner_bp
        print("Success partner")
    except Exception as e:
        print("Failed partner:")
        traceback.print_exc()

if __name__ == "__main__":
    test_imports()
