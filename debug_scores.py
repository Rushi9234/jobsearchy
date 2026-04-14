import sys
sys.path.insert(0, '.')
from utils.matcher import compute_score, explain_score
from utils.resume_parser import load_profile
from database.db import get_top_jobs

profile = load_profile()
jobs = get_top_jobs(limit=5)

print("Profile skills:", profile["summary"]["all_skills"][:10])
print("Year:", profile.get("year_of_study"))
print()

for job in jobs:
    detail = explain_score(profile, job)
    print(f"--- {job['title']} @ {job['company']}")
    print(f"    Total:{detail['total_score']}  Skill:{detail['skill_score']}  Cosine:{detail['cosine_score']}")
    print(f"    Matched: {detail['matched_skills']}")
    print(f"    Overlap: {detail['skill_overlap']}")
    print(f"    Description preview: {job.get('description','')[:100]}")
    print()
