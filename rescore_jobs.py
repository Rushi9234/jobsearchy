import sqlite3
import json
import sys
sys.path.insert(0, '.')
from utils.matcher import batch_score

print("Loading profile...")
with open('profile.json', 'r') as f:
    profile = json.load(f)

print(f"Skills loaded: {len(profile.get('skills', []))}")

conn = sqlite3.connect('searchy.db')
cur = conn.cursor()

cur.execute("SELECT id, title, company, description, tags FROM jobs")
jobs = cur.fetchall()
print(f"Jobs to rescore: {len(jobs)}")

# Build job dicts
job_list = []
for row in jobs:
    jid, title, company, desc, tags = row
    try:
        tag_list = json.loads(tags) if tags else []
    except:
        tag_list = []
    job_list.append({
        'id': jid,
        'title': title or '',
        'company': company or '',
        'description': desc or '',
        'tags': tag_list
    })

# Score in batches
print("Scoring...")
scored = batch_score(profile, job_list)

# Update DB
updated = 0
for job in scored:
    cur.execute(
        "UPDATE jobs SET match_score=? WHERE id=?",
        (job.get('match_score', 0), job['id'])
    )
    updated += 1

conn.commit()
conn.close()

scores = [j.get('match_score', 0) for j in scored]
print(f"\n✅ Rescored {updated} jobs!")
print(f"   Min: {min(scores):.1f}")
print(f"   Max: {max(scores):.1f}")
print(f"   Avg: {sum(scores)/len(scores):.1f}")
print(f"   Above 50: {sum(1 for s in scores if s >= 50)}")
print(f"   Above 30: {sum(1 for s in scores if s >= 30)}")
