import sqlite3
import os

# Find the database file
db_path = None
for f in os.listdir('.'):
    if f.endswith('.db'):
        db_path = f
        print(f"Found: {f}")
        break

if not db_path:
    print("No .db file found in current directory!")
    # List all files
    for f in os.listdir('.'):
        print(f"  {f}")
    exit()

c = sqlite3.connect(db_path)

# Show existing tables
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
table_names = [t[0] for t in tables]
print(f"Tables: {table_names}")

# Find the challenge purchases table
cp_table = None
for t in table_names:
    if 'challenge' in t.lower() and 'purchase' in t.lower():
        cp_table = t
        break

if not cp_table:
    print("ERROR: Could not find challenge_purchase table!")
    exit()

print(f"Using table: {cp_table}")

# Show current columns
cols = c.execute(f"PRAGMA table_info({cp_table})").fetchall()
col_names = [col[1] for col in cols]
print(f"Columns before: {len(col_names)}")

# Add missing columns
missing = [
    ("lowest_equity_lifetime", "FLOAT"),
    ("lowest_equity_phase", "FLOAT"),
    ("violation_reviewed", "BOOLEAN DEFAULT 0"),
    ("last_violation_evidence_id", "INTEGER"),
]

for col_name, col_type in missing:
    if col_name not in col_names:
        try:
            c.execute(f"ALTER TABLE {cp_table} ADD COLUMN {col_name} {col_type}")
            print(f"  ADDED: {col_name}")
        except Exception as e:
            print(f"  ERROR: {col_name} - {e}")
    else:
        print(f"  EXISTS: {col_name}")

# Create violation_evidence table
print("\nCreating violation_evidence table...")
try:
    c.execute("""
        CREATE TABLE IF NOT EXISTS violation_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenge_purchase_id INTEGER NOT NULL,
            violation_type VARCHAR(50) NOT NULL,
            rule_name VARCHAR(100) NOT NULL,
            rule_limit FLOAT,
            actual_value FLOAT,
            balance FLOAT,
            equity FLOAT,
            floating_pnl FLOAT,
            profit_percent FLOAT,
            daily_drawdown FLOAT,
            overall_drawdown FLOAT,
            trading_days INTEGER,
            reason TEXT NOT NULL,
            severity VARCHAR(20) DEFAULT 'hard_breach',
            open_positions_snapshot TEXT,
            recent_trades_snapshot TEXT,
            account_snapshot_data TEXT,
            is_reviewed BOOLEAN DEFAULT 0,
            reviewed_by INTEGER,
            reviewed_at DATETIME,
            review_decision VARCHAR(50),
            review_notes TEXT,
            violation_timestamp DATETIME,
            created_at DATETIME
        )
    """)
    print("  CREATED violation_evidence table")
except Exception as e:
    print(f"  {e}")

c.commit()
c.close()
print("\nDONE - All fixed!")