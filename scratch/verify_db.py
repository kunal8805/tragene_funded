import sqlite3

def verify():
    conn = sqlite3.connect('instance/tragene_funded_new.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    print("Tables in migrated database:")
    print("  ", tables)
    
    cursor.execute("SELECT count(*) FROM user;")
    print(f"Users Count: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT count(*) FROM challenge_purchase;")
    print(f"Challenges Count: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT version_num FROM alembic_version;")
    print(f"Alembic Head Version: {cursor.fetchone()[0]}")
    
    cursor.execute("PRAGMA table_info(user);")
    user_cols = [c[1] for c in cursor.fetchall()]
    print("User Table columns:")
    for col in ['trading_alias', 'trader_level', 'is_compact_view']:
        print(f"   {col} present: {col in user_cols}")
        
    cursor.execute("PRAGMA table_info(challenge_purchase);")
    cp_cols = [c[1] for c in cursor.fetchall()]
    print("ChallengePurchase Table columns:")
    for col in ['challenge_type', 'current_phase', 'is_terminated']:
        print(f"   {col} present: {col in cp_cols}")
        
    conn.close()

if __name__ == '__main__':
    verify()
