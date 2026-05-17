import os
import shutil
import sqlite3
import subprocess

DB_PATH = 'instance/tragene_funded_new.db'
BACKUP_PATH = 'instance/tragene_funded_new.db.backup'
TEMP_ERR_BACKUP = 'instance/tragene_funded_new.db.err_backup'

def restore_and_migrate():
    print("[START] Starting Database Restore and Migration...")
    
    # 1. Back up current broken database
    if os.path.exists(DB_PATH):
        print(f"[BACKUP] Backing up current active database to {TEMP_ERR_BACKUP}...")
        if os.path.exists(TEMP_ERR_BACKUP):
            os.remove(TEMP_ERR_BACKUP)
        shutil.copy2(DB_PATH, TEMP_ERR_BACKUP)
        os.remove(DB_PATH)

    # 2. Restore from backup
    if not os.path.exists(BACKUP_PATH):
        print(f"[ERROR] Backup file not found at {BACKUP_PATH}!")
        return False
        
    print(f"[RESTORE] Restoring {BACKUP_PATH} to {DB_PATH}...")
    shutil.copy2(BACKUP_PATH, DB_PATH)

    # 3. Update alembic_version to baseline
    print("[STAMP] Updating alembic_version in the restored database to baseline '048c3585fd45'...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Verify the table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version';")
        if not cursor.fetchone():
            cursor.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);")
            cursor.execute("INSERT INTO alembic_version (version_num) VALUES ('048c3585fd45');")
        else:
            cursor.execute("UPDATE alembic_version SET version_num = '048c3585fd45';")
            
        conn.commit()
        
        # Read it back to verify
        cursor.execute("SELECT version_num FROM alembic_version;")
        print(f"[OK] Database stamped with alembic_version: {cursor.fetchone()[0]}")
        conn.close()
    except Exception as e:
        print(f"[ERROR] Error updating alembic_version: {e}")
        return False

    # 4. Run Flask migrations to bring it to the latest version
    print("[MIGRATE] Running python -m flask db upgrade...")
    try:
        res = subprocess.run(
            ['python', '-m', 'flask', 'db', 'upgrade'],
            capture_output=True,
            text=True
        )
        print("--- Standard Output ---")
        print(res.stdout)
        print("--- Error Output ---")
        print(res.stderr)
        
        if res.returncode == 0:
            print("[SUCCESS] Database migrated to latest revision successfully!")
            return True
        else:
            print("[ERROR] flask db upgrade command failed!")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to run upgrade subprocess: {e}")
        return False

if __name__ == '__main__':
    restore_and_migrate()
