import os
import sys

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, root_dir)

from app import app
from flask import url_for

with app.app_context():
    with app.test_request_context():
        try:
            url = url_for('user.dashboard')
            print(f"SUCCESS: url_for('user.dashboard') = {url}")
        except Exception as e:
            print(f"FAILED: {e}")
