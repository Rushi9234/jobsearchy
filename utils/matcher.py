"""
matcher.py — Searchy AI Match Scorer
Computes a 0–100 match score between a user profile and a job listing.
Uses TF-IDF cosine similarity (scikit-learn) + skill overlap bonus.
No API calls required — fully local and free.
"""

import re
import json
import math
import logging

logger = logging.getLogger(__name__)

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not found — using keyword-only scoring.")

W_COSINE    = 0.35
W_SKILL     = 0.40
W_EDUCATION = 0.15
W_YEAR      = 0.10

INTERNSHIP_KEYWORDS = {"intern", "internship", "trainee", "apprentice", "student"}
FRESHER_KEYWORDS    = {"fresher", "fresh graduate", "entry level", "0-1 year", "0 year", "recent graduate", "junior"}
FREELANCE_KEYWORDS  = {"freelance", "contract", "remote", "part-time", "project-based"}
HACKATHON_KEYWORDS  = {"hackathon", "competition", "challenge", "contest", "ideathon"}

SKILL_SYNONYMS = {
    "econometrics":            "economics statistics regression time series",
    "statsmodels":             "statistical modeling regression ols",
    "xgboost":                 "gradient boosting machine learning",
    "shap":                    "explainability model interpretation feature importance",
    "scipy":                   "scientific computing statistics",
    "adf":                     "augmented dickey fuller time series stationarity",
    "augmented dickey-fuller": "time series stationarity unit root test",
    "ols":                     "ordinary least squares regression linear model",
    "smote":                   "oversampling imbalanced data classification",
    "power bi":                "business intelligence dashboard visualization",
    "scikit-learn":            "machine learning sklearn classification regression",
}


def _get_skills(profile: dict) -> list:
    """Always returns a flat list of skills regardless of profile format."""
    skills = profile.get("skills", [])
    if isinstance(skills, dict):
        return skills.get("technical", []) + skills.get("soft", [])
    if isinstance(skills, list):
        return skills
    return []


def _clean(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s\+\#]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _cosine_score(profile_text: str, job_text: str) -> float:
    if not SKLEARN_AVAILABLE or not profile_text or not job_text:
        return 0.0
    try:
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=5000, sublinear_tf=True)
        matrix = vectorizer.fit_transform([profile_text, job_text])
        return float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])
    except Exception as e:
        logger.debug("TF-IDF error: %s", e)
        return 0.0


def _skill_overlap_score(profile_skills: list, job_text: str) -> float:
    if not profile_skills:
        return 0.0
    job_lower = job_text.lower()

    job_skill_tokens = re.findall(
        r'\b(?:python|java|react|node|flask|django|sql|ml|ai|git|docker|'
        r'kubernetes|aws|gcp|azure|tensorflow|pytorch|nlp|data|api|rest|'
        r'javascript|typescript|css|html|mongodb|postgresql|redis|'
        r'scikit|pandas|numpy|opencv|keras|linux|bash|c\+\+|golang|rust|'
        r'spark|hadoop|tableau|power\s?bi|figma|selenium|scrapy|'
        r'xgboost|lightgbm|statsmodels|scipy|shap|econometrics|'
        r'regression|forecasting|analytics|visualization|excel|r\b|matlab|'
        r'statistics|quantitative|research|analysis|modeling)\b',
        job_lower
    )
    num_job_skills = max(len(set(job_skill_tokens)), 3)

    matched = sum(
        1 for skill in profile_skills
        if re.search(r"\b" + re.escape(skill.lower()) + r"\b", job_lower)
    )
    if matched == 0:
        return 0.0

    denominator = math.sqrt(min(len(profile_skills), num_job_skills * 2))
    score = min(matched / denominator, 1.0)
    return max(score, 0.25)


def _education_score(profile: dict, job_text: str) -> float:
    job_lower = job_text.lower()
    edu = profile.get("education", [])
    if not edu:
        return 0.5

    candidate_degrees = {(e.get("degree") or "").lower() for e in edu}

    if any(deg in ["b.tech", "btech", "be", "b.e", "bsc"] for deg in candidate_degrees):
        if any(kw in job_lower for kw in ["btech", "b.tech", "b.e", "engineering", "undergraduate"]):
            return 1.0
        if any(kw in job_lower for kw in ["mtech", "phd", "master", "postgrad"]):
            return 0.2
        return 0.7

    return 0.5


def _year_of_study_score(profile: dict, job_text: str) -> float:
    year = profile.get("year_of_study")
    job_lower = job_text.lower()

    if not year:
        return 0.5

    is_intern_role  = any(kw in job_lower for kw in INTERNSHIP_KEYWORDS)
    is_fresher_role = any(kw in job_lower for kw in FRESHER_KEYWORDS)

    if year in (1, 2) and is_intern_role:
        return 1.0
    if year == 3 and (is_intern_role or is_fresher_role):
        return 1.0
    if year == 4 and (is_fresher_role or is_intern_role):
        return 1.0
    if is_intern_role or is_fresher_role:
        return 0.7
    return 0.5


def _build_profile_text(profile: dict) -> str:
    parts = []
    parts.append(profile.get("name", ""))
    if profile.get("college"):
        parts.append(profile["college"])
    if profile.get("current_course"):
        parts.append(profile["current_course"])

    skills = _get_skills(profile)
    parts.extend(skills)

    for edu in profile.get("education", []):
        parts.append(edu.get("institution", ""))
        parts.append(edu.get("degree") or "")

    for p in profile.get("projects", []):
        if isinstance(p, dict):
            parts.append(p.get("title", ""))
            parts.append(p.get("description", ""))
        else:
            parts.append(str(p))

    parts.extend(profile.get("experience", []))
    parts.extend(profile.get("certifications", []))

    for skill in skills:
        if skill.lower() in SKILL_SYNONYMS:
            parts.append(SKILL_SYNONYMS[skill.lower()])

    return _clean(" ".join(filter(None, parts)))


def compute_score(profile: dict, job: dict) -> float:
    raw_tags = job.get("tags", [])
    if isinstance(raw_tags, str):
        try:
            raw_tags = json.loads(raw_tags)
        except:
            raw_tags = []

    job_text = " ".join(filter(None, [
        job.get("title", ""),
        job.get("description", ""),
        job.get("company", ""),
        " ".join(raw_tags) if isinstance(raw_tags, list) else "",
    ]))
    if not job_text.strip():
        return 0.0

    job_clean     = _clean(job_text)
    profile_clean = _build_profile_text(profile)
    all_skills    = profile.get("summary", {}).get("all_skills", []) or _get_skills(profile)

    cosine = _cosine_score(profile_clean, job_clean)
    skill  = _skill_overlap_score(all_skills, job_clean)
    edu    = _education_score(profile, job_clean)
    yr     = _year_of_study_score(profile, job_clean)

    raw = (W_COSINE * cosine + W_SKILL * skill + W_EDUCATION * edu + W_YEAR * yr)
    return round(min(raw * 100, 100.0), 2)


def batch_score(profile: dict, jobs: list) -> list:
    for job in jobs:
        job["match_score"] = compute_score(profile, job)
    return sorted(jobs, key=lambda j: j["match_score"], reverse=True)


def explain_score(profile: dict, job: dict) -> dict:
    raw_tags = job.get("tags", [])
    if isinstance(raw_tags, str):
        try:
            raw_tags = json.loads(raw_tags)
        except:
            raw_tags = []

    job_text = " ".join(filter(None, [
        job.get("title", ""),
        job.get("description", ""),
        " ".join(raw_tags) if isinstance(raw_tags, list) else "",
    ]))
    job_clean     = _clean(job_text)
    profile_clean = _build_profile_text(profile)
    all_skills    = profile.get("summary", {}).get("all_skills", []) or _get_skills(profile)

    matched_skills = [
        s for s in all_skills
        if re.search(r"\b" + re.escape(s.lower()) + r"\b", job_clean)
    ]
    missing_skills = [s for s in all_skills if s not in matched_skills]

    cosine = _cosine_score(profile_clean, job_clean)
    skill  = _skill_overlap_score(all_skills, job_clean)
    edu    = _education_score(profile, job_clean)
    yr     = _year_of_study_score(profile, job_clean)
    total  = compute_score(profile, job)

    return {
        "total_score":     total,
        "cosine_score":    round(cosine * 100, 1),
        "skill_score":     round(skill * 100, 1),
        "education_score": round(edu * 100, 1),
        "year_score":      round(yr * 100, 1),
        "matched_skills":  matched_skills,
        "missing_skills":  missing_skills[:10],
        "skill_overlap":   f"{len(matched_skills)}/{len(all_skills)}",
    }


if __name__ == "__main__":
    sample_profile = {
        "name": "Rushikesh Baban Kedar",
        "skills": ["python", "pandas", "numpy", "scikit-learn", "xgboost",
                   "statsmodels", "scipy", "econometrics", "matplotlib", "tableau"],
        "education": [{"institution": "MITAOE Pune", "degree": "BTECH", "year": 2027}],
        "year_of_study": 3,
        "projects": [
            {"title": "Credit Risk Prediction", "description": "XGBoost SMOTE AUC-ROC classification"},
        ],
        "experience": [],
        "certifications": [],
        "summary": {"all_skills": ["python", "pandas", "xgboost", "scikit-learn", "econometrics"]},
    }
    sample_job = {
        "title": "Data Science Intern",
        "company": "Analytics Corp",
        "description": "Looking for a B.Tech student with Python, pandas, scikit-learn, machine learning skills.",
        "tags": ["python", "data science", "internship", "machine learning"],
    }
    score = compute_score(sample_profile, sample_job)
    detail = explain_score(sample_profile, sample_job)
    print(f"Score: {score}")
    print(json.dumps(detail, indent=2))
