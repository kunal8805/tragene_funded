import sqlite3
c = sqlite3.connect(r'instance\tragene_funded_new.db')
c.execute("DROP TABLE IF EXISTS _alembic_tmp_challenge_purchase")
c.commit()
c.close()
print("done")
