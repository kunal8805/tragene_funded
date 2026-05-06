"""
Database migration script to add document_number column to User table.
Run this script once to update the existing database schema.
"""
import sqlite3
import os

# Database path
DB_PATH = 'instance/tragene_funded_new.db'

def add_document_number_column():
    """Add document_number column to User table if it doesn't exist"""
    
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database not found at {DB_PATH}")
        print("   The column will be created when you first run the app.")
        return
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(user)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'document_number' in columns:
            print("[OK] Column 'document_number' already exists in User table")
        else:
            # Add the column
            cursor.execute("ALTER TABLE user ADD COLUMN document_number VARCHAR(50) DEFAULT ''")
            conn.commit()
            print("[OK] Successfully added 'document_number' column to User table")
        
        conn.close()
        
    except Exception as e:
        print(f"[ERROR] Error updating database: {e}")
        print("   You may need to recreate the database or run migrations manually.")

if __name__ == '__main__':
    print("Adding document_number column to database...")
    add_document_number_column()
    print("Migration complete!")
