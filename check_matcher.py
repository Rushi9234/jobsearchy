import json, sys
sys.path.insert(0, '.')
from utils.matcher import compute_score, explain_score

# Load actual profile.json
with open('profile.json') as f:
    profile = json.load(f)

print("Skills type:", type(profile.get('skills')))
print("Skills count:", len(profile.get('skills', [])))
print("Summary all_skills count:", len(profile.get('summary', {}).get('all_skills', [])))

test_job = {
    'title': 'Data Science Intern',
    'company': 'Analytics Corp',
    'description': 'Looking for a B.Tech student with Python, pandas, numpy, scikit-learn, machine learning, XGBoost, data analysis internship.',
    'tags': ['python', 'data science', 'machine learning', 'pandas', 'xgboost', 'internship']
}

score = compute_score(profile, test_job)
detail = explain_score(profile, test_job)
print(f"\nTest job score: {score}")
print("Breakdown:", json.dumps(detail, indent=2))