import sqlite3
c = sqlite3.connect(r'instance\tragene_funded_new.db')
rows = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '_alembic_tmp_%'").fetchall()
print(rows)
