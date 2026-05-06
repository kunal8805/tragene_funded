
import sqlite3
import os

DB_PATH = 'instance/tragene_funded_new.db'

def dump_schema():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    tables_to_check = ['user', 'challenge_purchase', 'alembic_version']
    
    for table_name in tables_to_check:
        print(f"\n--- TABLE: {table_name} ---")
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            for col in columns:
                print(col)
            
            if table_name == 'alembic_version':
                cursor.execute(f"SELECT * FROM {table_name}")
                print(f"Current version: {cursor.fetchone()}")
        except Exception as e:
            print(f"Error checking {table_name}: {e}")
            
    conn.close()

if __name__ == "__main__":
    dump_schema()
