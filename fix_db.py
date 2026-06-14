import sqlite3
conn = sqlite3.connect('instance/tragene_funded_new.db')
cur = conn.cursor()
cur.execute('PRAGMA table_info(notification)')
existing = {row[1] for row in cur.fetchall()}
print('Existing columns:', existing)
cols = [
    ('notification_type', 'VARCHAR(50) DEFAULT NULL'),
    ('action_url', 'VARCHAR(500)'),
    ('icon', 'VARCHAR(100)'),
    ('dedupe_key', 'VARCHAR(200)'),
    ('is_deleted', 'BOOLEAN DEFAULT 0 NOT NULL'),
    ('created_by_admin_id', 'INTEGER'),
]
for name, defn in cols:
    if name not in existing:
        cur.execute('ALTER TABLE notification ADD COLUMN ' + name + ' ' + defn)
        print('Added: ' + name)
    else:
        print('Skipped: ' + name)
conn.commit()
conn.close()
print('Done!')
