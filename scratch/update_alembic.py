import os
import sys

# Add root folder to sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, root_dir)

from app import app, db

with app.app_context():
    db.session.execute(db.text("UPDATE alembic_version SET version_num = '9e6acc10156b'"))
    db.session.commit()
    print("Alembic version successfully updated to 9e6acc10156b.")
