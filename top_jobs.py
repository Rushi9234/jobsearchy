import sqlite3
conn = sqlite3.connect('searchy.db')
cur = conn.cursor()
cur.execute('SELECT title, company, match_score, source FROM jobs ORDER BY match_score DESC LIMIT 10')
print(f"{'Score':<7} {'Title':<45} {'Company':<25} {'Source'}")
print("-" * 90)
for r in cur.fetchall():
    print(f"{r[2]:<7.1f} {str(r[0])[:45]:<45} {str(r[1])[:25]:<25} {r[3]}")
conn.close()
