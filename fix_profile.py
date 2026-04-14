import json

with open('profile.json', 'r') as f:
    p = json.load(f)

# Fix skills: flatten dict → list
if isinstance(p.get('skills'), dict):
    technical = p['skills'].get('technical', [])
    soft = p['skills'].get('soft', [])
    p['skills'] = list(set(technical + soft))

# Fix summary skills too
p['summary']['all_skills'] = p['skills']

# Fix education: remove lines that are clearly project/description text
clean_edu = []
for e in p.get('education', []):
    inst = e.get('institution', '')
    if inst.startswith('•') or 'SMOTE' in inst or 'XGBoost' in inst or 'AUC' in inst:
        continue
    clean_edu.append(e)
p['education'] = clean_edu

# Add projects manually from your resume (parser missed them)
p['projects'] = [
    {
        "title": "Credit Risk Prediction",
        "description": "Applied SMOTE for class imbalance, XGBoost final model, AUC-ROC 0.7969",
        "skills": ["xgboost", "smote", "scikit-learn", "python"]
    },
    {
        "title": "Econometrics Research",
        "description": "Time series analysis using ADF, OLS regression, statsmodels, scipy",
        "skills": ["econometrics", "statsmodels", "scipy", "python", "r"]
    }
]
p['summary']['num_projects'] = len(p['projects'])

with open('profile.json', 'w') as f:
    json.dump(p, f, indent=2)

print("✅ profile.json fixed!")
print(f"   Skills: {len(p['skills'])} → {p['skills'][:5]}...")
print(f"   Projects: {len(p['projects'])}")
print(f"   Education entries: {len(p['education'])}")