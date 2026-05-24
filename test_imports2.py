import traceback

print("Testing blog_bp...")
try:
    from blog import blog_bp
    print("Success blog")
except Exception as e:
    print("Failed blog:")
    traceback.print_exc()

print("Testing admin_blog_bp...")
try:
    from admin_blog import admin_blog_bp
    print("Success admin_blog")
except Exception as e:
    print("Failed admin_blog:")
    traceback.print_exc()

print("Testing receiver_bp...")
try:
    from mt5_receiver import receiver_bp
    print("Success receiver")
except Exception as e:
    print("Failed receiver:")
    traceback.print_exc()
