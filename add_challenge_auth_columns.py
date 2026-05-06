"""
Database migration script to add challenge authentication columns.

Adds:
- serial_no: Sequential tracking number starting from 1111
- challenge_code: 6-digit numeric EA identifier
- challenge_token: Cryptographically secure authentication token

Also backfills existing purchases with these values.
"""
import sqlite3
import os
import sys
import secrets
import random

# Database path
DB_PATH = 'instance/tragene_funded_new.db'


def add_challenge_auth_columns():
    """Add authentication columns to ChallengePurchase table"""
    
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database not found at {DB_PATH}")
        print("   The columns will be created when you first run the app.")
        return
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check existing columns
        cursor.execute("PRAGMA table_info(challenge_purchase)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add serial_no column
        if 'serial_no' not in columns:
            cursor.execute("ALTER TABLE challenge_purchase ADD COLUMN serial_no INTEGER")
            print("[OK] Added 'serial_no' column")
        else:
            print("[INFO] Column 'serial_no' already exists")
        
        # Add challenge_code column
        if 'challenge_code' not in columns:
            cursor.execute("ALTER TABLE challenge_purchase ADD COLUMN challenge_code VARCHAR(6)")
            print("[OK] Added 'challenge_code' column")
        else:
            print("[INFO] Column 'challenge_code' already exists")
        
        # Add challenge_token column
        if 'challenge_token' not in columns:
            cursor.execute("ALTER TABLE challenge_purchase ADD COLUMN challenge_token VARCHAR(100)")
            print("[OK] Added 'challenge_token' column")
        else:
            print("[INFO] Column 'challenge_token' already exists")
        
        conn.commit()
        
        # Backfill existing purchases
        print("\n[INFO] Backfilling existing purchases...")
        cursor.execute("SELECT id FROM challenge_purchase WHERE serial_no IS NULL ORDER BY id")
        purchases = cursor.fetchall()
        
        if purchases:
            serial_start = 1111
            used_codes = set()
            used_tokens = set()
            
            for idx, (purchase_id,) in enumerate(purchases):
                # Generate unique serial_no
                serial = serial_start + idx
                
                # Generate unique challenge_code
                while True:
                    code = str(random.randint(100000, 999999))
                    if code not in used_codes:
                        used_codes.add(code)
                        break
                
                # Generate unique challenge_token
                while True:
                    token = secrets.token_hex(32)
                    if token not in used_tokens:
                        used_tokens.add(token)
                        break
                
                # Update purchase
                cursor.execute("""
                    UPDATE challenge_purchase 
                    SET serial_no = ?, challenge_code = ?, challenge_token = ?
                    WHERE id = ?
                """, (serial, code, token, purchase_id))
            
            conn.commit()
            print(f"[OK] Backfilled {len(purchases)} existing purchases")
        else:
            print("[INFO] No existing purchases to backfill")
        
        conn.close()
        print("\n[SUCCESS] Migration completed successfully!")
        
    except Exception as e:
        print(f"[ERROR] Migration failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    print("Adding challenge authentication columns to database...")
    print("=" * 60)
    add_challenge_auth_columns()
