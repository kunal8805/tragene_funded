import os
import sys
import sqlite3

# Add current working directory to sys.path
sys.path.append(os.getcwd())

from app import app, db

def compare():
    db_path = os.path.abspath('instance/tragene_funded_new.db')
    print('DB File absolute path:', db_path)
    print('DB File exists:', os.path.exists(db_path))
    print('DB File size:', os.path.getsize(db_path) if os.path.exists(db_path) else 'N/A')

    # sqlite3 connection
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print('sqlite3 tables:', [r[0] for r in cursor.fetchall()])
    conn.close()

    # SQLAlchemy connection
    with app.app_context():
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        print('SQLAlchemy engine URL:', db.engine.url)
        print('SQLAlchemy tables:', inspector.get_table_names())

if __name__ == '__main__':
    compare()
