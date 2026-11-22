"""
matcher.py — Searchy AI Match Scorer (v2)
Computes a 0–100 match score + separate coverage score between profile and job.

v2 improvements (Apr 17, 2026):
  • Fuzzy skill matching via rapidfuzz (python3 ≈ python, sklearn ≈ scikit-learn)
  • Skill frequency weighting (more mentions = stronger signal)
  • Description length penalty (short JDs can't dominate)
  • Score calibration (stretches 60-67 cluster to 75-88)
  • Skill prominence weighting (explicit skills > inferred from projects)
  • Expanded SKILL_SYNONYMS dictionary
  • Batched TF-IDF (1 call for N jobs, memory-safe for Render free tier)
  • COVERAGE SCORE (new) — what % of a job's required skills user already has
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

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    logger.warning("rapidfuzz not found — using exact skill matching only.")


# ── Weights ──────────────────────────────────────────────────────────────────
W_COSINE    = 0.30
W_SKILL     = 0.45
W_EDUCATION = 0.15
W_YEAR      = 0.10

INTERNSHIP_KEYWORDS = {"intern", "internship", "trainee", "apprentice", "student"}
FRESHER_KEYWORDS    = {"fresher", "fresh graduate", "entry level", "0-1 year",
                       "0 year", "recent graduate", "junior"}
HACKATHON_KEYWORDS  = {"hackathon", "competition", "challenge", "contest", "ideathon"}


# ── Skill synonyms (expanded) ────────────────────────────────────────────────
SKILL_SYNONYMS = {
    "econometrics":       "economics statistics regression time series",
    "statsmodels":        "statistical modeling regression ols",
    "xgboost":            "gradient boosting machine learning xgb",
    "lightgbm":           "gradient boosting lgbm",
    "shap":               "explainability interpretation feature importance",
    "scipy":              "scientific computing statistics",
    "smote":              "oversampling imbalanced classification",
    "power bi":           "business intelligence dashboard powerbi visualization",
    "scikit-learn":       "machine learning sklearn classification regression",
    "tensorflow":         "deep learning neural networks tf keras",
    "pytorch":            "deep learning neural networks torch",
    "nlp":                "natural language processing text analytics",
    "computer vision":    "cv opencv image processing",
    "transformers":       "huggingface bert gpt attention",
    "pandas":             "dataframe data manipulation",
    "numpy":              "numerical arrays",
    "matplotlib":         "plotting visualization charts",
    "seaborn":            "statistical visualization",
    "plotly":             "interactive visualization dashboards",
    "gradio":             "ml demo ui web interface",
    "mongodb":            "nosql document database",
    "mysql":              "relational database sql",
    "postgresql":         "relational database sql postgres",
    "machine learning":   "ml ai predictive modeling",
    "deep learning":      "neural networks dl cnn rnn lstm",
    "data analysis":      "eda exploratory analytics",
    "data visualisation": "dataviz charts dashboards",
    "data visualization": "dataviz charts dashboards",
    "git":                "version control",
    "github":             "git hosting version control",
    "jupyter":            "notebook ipynb interactive",
    "colab":              "google colab notebook gpu",
    "imbalanced-learn":   "imblearn oversampling smote",
    "java":               "jvm spring",
    "c":                  "systems programming",
    "c++":                "cpp systems programming stl",
    "react":              "reactjs frontend javascript jsx",
    "flask":              "python web framework backend api",
    "django":             "python web framework backend orm",
    "docker":             "containerization devops",
    "kubernetes":         "k8s orchestration containers",
    "aws":                "amazon web services cloud ec2 s3",
    "gcp":                "google cloud platform",
    "azure":              "microsoft cloud",
    "sql":                "database query rdbms",
    "fastapi":            "python async api framework",
    "streamlit":          "python dashboard ml web app",
}

# Short skills that shouldn't fuzzy-match (prevents 'c' matching everything)
SHORT_SKILLS_EXACT_ONLY = {"c", "r", "go", "ai", "ml", "cv", "ui", "ux", "js", "ts"}

# Known skill vocabulary for extracting "required skills" from JDs
JOB_SKILL_VOCABULARY = {
    "python","java","c","c++","javascript","typescript","go","rust","kotlin","swift","r",
    "html","css","react","angular","vue","bootstrap","tailwind",
    "django","flask","fastapi","spring","express","node.js","nodejs","rest","graphql","api",
    "pandas","numpy","matplotlib","seaborn","scikit-learn","sklearn","scipy",
    "tensorflow","pytorch","keras","opencv","nltk","spacy","huggingface","transformers",
    "langchain","llm","machine learning","deep learning","data science","nlp",
    "computer vision","xgboost","lightgbm","catboost","classification","regression",
    "clustering","neural network","cnn","rnn","lstm","bert","gpt",
    "mysql","postgresql","postgres","mongodb","sqlite","redis","sql","nosql",
    "aws","gcp","azure","docker","kubernetes","linux","git","github","ci/cd",
    "android","ios","flutter","react native",
    "excel","tableau","power bi","powerbi","figma",
    "shap","smote","gradio","streamlit","jupyter","colab","statsmodels","plotly",
    "data analysis","data visualization","data visualisation",
    "airflow","spark","kafka","selenium","beautifulsoup","scrapy","requests",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_skills(profile: dict) -> list:
    skills = profile.get("skills", [])
    if isinstance(skills, dict):
        return skills.get("technical", []) + skills.get("soft", [])
    if isinstance(skills, list):
        return skills
    return []


def _clean(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("c/c++", "c++")
    # Protect dots and slashes inside technical tokens (e.g. node.js, ci/cd, b.tech)
    text = re.sub(r"(?<=[a-z0-9])\.(?=[a-z0-9])", "zzdotzz", text)
    text = re.sub(r"(?<=[a-z0-9])/(?=[a-z0-9])", "zzslashzz", text)
    # Strip non-alphanumeric except +, #, -
    text = re.sub(r"[^a-z0-9\s\+\#\-]", " ", text)
    # Restore protected technical dots and slashes
    text = text.replace("zzdotzz", ".").replace("zzslashzz", "/")
    return re.sub(r"\s+", " ", text).strip()


def _get_prominent_skills(profile: dict) -> set:
    """Explicit skills are prominent — those in 'skills_explicit' or 'skills'."""
    explicit = profile.get("skills_explicit")
    if explicit and isinstance(explicit, list):
        return {s.lower() for s in explicit}
    return {s.lower() for s in _get_skills(profile)}


def _build_profile_text(profile: dict) -> str:
    parts = [profile.get("name", "")]
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

    for e in profile.get("experience", []):
        if isinstance(e, dict):
            parts.append(e.get("role", ""))
            parts.append(e.get("company", ""))
            parts.append(e.get("description", ""))
        else:
            parts.append(str(e))

    for c in profile.get("certifications", []):
        if isinstance(c, dict):
            parts.append(c.get("name", ""))
        else:
            parts.append(str(c))

    for skill in skills:
        if skill.lower() in SKILL_SYNONYMS:
            parts.append(SKILL_SYNONYMS[skill.lower()])

    return _clean(" ".join(filter(None, parts)))


def _build_job_text(job: dict) -> str:
    raw_tags = job.get("tags", [])
    if isinstance(raw_tags, str):
        try:
            raw_tags = json.loads(raw_tags)
        except Exception:
            raw_tags = []
    return _clean(" ".join(filter(None, [
        job.get("title", ""),
        job.get("description", ""),
        job.get("company", ""),
        " ".join(raw_tags) if isinstance(raw_tags, list) else "",
    ])))


# ── TF-IDF / cosine ──────────────────────────────────────────────────────────

def _cosine_score(profile_text: str, job_text: str) -> float:
    if not SKLEARN_AVAILABLE or not profile_text or not job_text:
        return 0.0
    try:
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=3000, sublinear_tf=True)
        matrix = vectorizer.fit_transform([profile_text, job_text])
        return float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])
    except Exception as e:
        logger.debug("TF-IDF error: %s", e)
        return 0.0


# ── Skill matching (fuzzy + frequency) ───────────────────────────────────────

def _count_skill_mentions(skill: str, text: str) -> int:
    """
    Count how many times a skill appears in the job text.
    Uses exact regex for short skills, fuzzy for longer technical terms.
    """
    skill_lower = skill.lower().strip()
    if not skill_lower:
        return 0

    # Exact regex first
    exact_pattern = r"\b" + re.escape(skill_lower) + r"\b"
    exact_matches = len(re.findall(exact_pattern, text))
    if exact_matches > 0:
        return exact_matches

    # Fuzzy only for non-short skills
    if skill_lower in SHORT_SKILLS_EXACT_ONLY or len(skill_lower) <= 2:
        return 0
    if not RAPIDFUZZ_AVAILABLE:
        return 0

    tokens = set(re.findall(r"\b[a-z][a-z0-9\+\-#\.]{1,30}\b", text))
    hits = 0
    for tok in tokens:
        if len(tok) < 3:
            continue
        if abs(len(tok) - len(skill_lower)) > max(3, len(skill_lower) // 2):
            continue
        if fuzz.ratio(skill_lower, tok) >= 88:
            hits += len(re.findall(r"\b" + re.escape(tok) + r"\b", text))
    return hits


def _skill_overlap_score(profile_skills: list, job_text: str,
                         prominent_skills: set = None) -> float:
    """
    Skill overlap with fuzzy matching, frequency weighting, and prominence boost.
    """
    if not profile_skills:
        return 0.0
    prominent_skills = prominent_skills or set()

    job_skill_tokens = re.findall(
        r"\b(?:python|java|react|node|flask|django|sql|ml|ai|git|docker|"
        r"kubernetes|aws|gcp|azure|tensorflow|pytorch|nlp|api|rest|"
        r"javascript|typescript|css|html|mongodb|postgresql|redis|"
        r"scikit|pandas|numpy|opencv|keras|linux|bash|c\+\+|golang|rust|"
        r"spark|hadoop|tableau|power\s?bi|figma|selenium|scrapy|"
        r"xgboost|lightgbm|statsmodels|scipy|shap|econometrics|"
        r"regression|forecasting|analytics|visualization|excel|matlab|"
        r"statistics|quantitative|research|analysis|modeling|transformers|"
        r"gradio|streamlit|fastapi|jupyter|colab|smote|seaborn|matplotlib|plotly)\b",
        job_text,
    )
    num_job_skills = max(len(set(job_skill_tokens)), 3)

    total_weight = 0.0
    matched_count = 0
    for skill in profile_skills:
        mentions = _count_skill_mentions(skill, job_text)
        if mentions <= 0:
            continue
        matched_count += 1
        # Diminishing returns on mentions: 1→1.0, 2→1.3, 3→1.5, capped 1.7
        mention_weight = min(1.0 + 0.3 * math.log2(max(mentions, 1) + 1), 1.7)
        prominence_mult = 1.2 if skill.lower() in prominent_skills else 1.0
        total_weight += mention_weight * prominence_mult

    if matched_count == 0:
        return 0.0

    # Scale-aware denominator: match proportional to the larger skill set
    effective_size = max(len(profile_skills), num_job_skills, 8)
    denominator = math.sqrt(effective_size)
    score = min(total_weight / denominator, 1.0)

    # Floor boost scales with how many skills matched
    if matched_count >= 5:
        return max(score, 0.40)
    elif matched_count >= 3:
        return max(score, 0.25)
    elif matched_count >= 2:
        return max(score, 0.15)
    return score  # single match — no floor


# ── Education + Year scoring ────────────────────────────────────────────────

def _education_score(profile: dict, job_text: str) -> float:
    edu = profile.get("education", [])
    if not edu:
        return 0.5
    candidate_degrees = {(e.get("degree") or "").lower() for e in edu}
    if any(deg in ["b.tech", "btech", "be", "b.e", "bsc"] for deg in candidate_degrees):
        if any(kw in job_text for kw in ["btech", "b.tech", "b.e", "engineering", "undergraduate"]):
            return 1.0
        if any(kw in job_text for kw in ["mtech", "phd", "master", "postgrad"]):
            return 0.2
        return 0.7
    return 0.5


def _year_of_study_score(profile: dict, job_text: str) -> float:
    year = profile.get("year_of_study")
    if not year:
        return 0.5
    is_intern = any(kw in job_text for kw in INTERNSHIP_KEYWORDS)
    is_fresher = any(kw in job_text for kw in FRESHER_KEYWORDS)
    if year in (1, 2) and is_intern:
        return 1.0
    if year == 3 and (is_intern or is_fresher):
        return 1.0
    if year == 4 and (is_fresher or is_intern):
        return 1.0
    if is_intern or is_fresher:
        return 0.7
    return 0.5


# ── Description length penalty ──────────────────────────────────────────────

def _description_length_factor(job_text: str) -> float:
    """Short JDs get a cosine multiplier penalty (can't trust sparse text)."""
    words = len(job_text.split())
    if words >= 80:
        return 1.0
    if words >= 40:
        return 0.85
    if words >= 15:
        return 0.70
    return 0.50


# ── Score calibration ───────────────────────────────────────────────────────

def _calibrate_score(raw_pct: float) -> float:
    """
    Stretches middle scores so genuinely good matches land in 75-88 range.
    Bad matches stay honest.
        raw 20 → 20   |  raw 50 → 58   |  raw 70 → 82   |  raw 85 → 94
    """
    if raw_pct <= 30:
        return raw_pct
    x = max(0.0, min(1.0, (raw_pct - 30) / 70))
    boost = 22.0 * math.sin(math.pi * x) * (0.5 + 0.5 * x)
    return min(raw_pct + boost, 99.0)


# ── Coverage Score (Rushi's idea) ───────────────────────────────────────────
# "If user has ALL the skills a job needs → 100% coverage → apply immediately."
# Separate from match score, answers "can I apply now with confidence?"

REQUIRED_SKILL_TRIGGERS = [
    r"skills?\s*required", r"required\s*skills?", r"must\s*(?:have|know)",
    r"requirements?", r"prerequisites?", r"qualifications?",
    r"you\s*should\s*know", r"you\s*need\s*to\s*know",
    r"mandatory\s*skills?", r"core\s*skills?",
    r"technical\s*skills?", r"key\s*skills?",
]


def _extract_required_skills(job_text: str) -> list:
    """
    Extract skills the JOB requires, as a list of lowercase skill names.
    Strategy:
      1. Look for explicit "skills required:" section — parse that.
      2. Fallback — all skills from vocabulary that appear in the JD.
    """
    # Strategy 1: explicit section
    for pat in REQUIRED_SKILL_TRIGGERS:
        m = re.search(pat + r"\s*[:\-–]?\s*(.{0,400})", job_text, re.IGNORECASE)
        if m:
            section = m.group(1).lower()
            found = {s for s in JOB_SKILL_VOCABULARY
                     if re.search(r"\b" + re.escape(s) + r"\b", section)}
            if len(found) >= 2:
                return sorted(found)

    # Strategy 2: all mentions in full text
    return sorted({s for s in JOB_SKILL_VOCABULARY
                   if re.search(r"\b" + re.escape(s) + r"\b", job_text)})


# Loose matching between a required skill and the user's skill set
SYNONYM_GROUPS = [
    {"scikit-learn", "sklearn"},
    {"node.js", "nodejs"},
    {"next.js", "nextjs"},
    {"c++", "cpp"},
    {"postgresql", "postgres"},
    {"power bi", "powerbi"},
    {"ml", "machine learning"},
    {"dl", "deep learning"},
    {"cv", "computer vision"},
    {"nlp", "natural language processing"},
    {"data visualisation", "data visualization", "dataviz"},
    {"js", "javascript"},
    {"ts", "typescript"},
    {"k8s", "kubernetes"},
]

# Category aliases — if JD says "ml", any of these satisfies it
CATEGORY_ALIASES = {
    "machine learning": {"scikit-learn", "sklearn", "xgboost", "lightgbm", "tensorflow", "pytorch", "keras"},
    "ml":               {"machine learning", "scikit-learn", "sklearn", "xgboost", "tensorflow", "pytorch"},
    "deep learning":    {"tensorflow", "pytorch", "keras", "transformers"},
    "nlp":              {"transformers", "huggingface", "nltk", "spacy"},
    "computer vision":  {"opencv", "pytorch", "tensorflow"},
    "data visualization": {"matplotlib", "seaborn", "plotly", "tableau", "power bi"},
    "data visualisation": {"matplotlib", "seaborn", "plotly", "tableau", "power bi"},
    "sql":              {"mysql", "postgresql", "sqlite", "postgres"},
}


def _skill_matches_profile(required_skill: str, profile_skills_lower: set) -> bool:
    """Does the user's skill set satisfy this required skill?"""
    req = required_skill.lower().strip()

    # 1. Exact match
    if req in profile_skills_lower:
        return True

    # 2. Synonym groups (bidirectional)
    for group in SYNONYM_GROUPS:
        if req in group and profile_skills_lower & group:
            return True

    # 3. Category aliases (e.g. "ml" satisfied by "scikit-learn")
    if req in CATEGORY_ALIASES:
        if CATEGORY_ALIASES[req] & profile_skills_lower:
            return True

    # 4. Fuzzy match for longer skills
    if RAPIDFUZZ_AVAILABLE and len(req) >= 4:
        for ps in profile_skills_lower:
            if len(ps) >= 4 and fuzz.ratio(req, ps) >= 88:
                return True

    return False


def coverage_score(profile_skills: list, job: dict) -> dict:
    """
    Computes what fraction of the job's REQUIRED skills the user has.
    Separate from match score — answers "can I confidently apply?"

    Returns dict with: coverage_pct, required_count, matched_count,
                       matched (list), missing (list), level.
    """
    job_text = _build_job_text(job)
    if not job_text:
        return {"coverage_pct": 0.0, "required_count": 0, "matched_count": 0,
                "matched": [], "missing": [], "level": "none"}

    required = _extract_required_skills(job_text)
    if not required:
        return {"coverage_pct": 0.0, "required_count": 0, "matched_count": 0,
                "matched": [], "missing": [], "level": "none"}

    profile_lower = {s.lower().strip() for s in profile_skills}
    matched, missing = [], []
    for req in required:
        if _skill_matches_profile(req, profile_lower):
            matched.append(req)
        else:
            missing.append(req)

    pct = round(100.0 * len(matched) / len(required), 1)
    if pct >= 90:
        level = "excellent"
    elif pct >= 70:
        level = "good"
    elif pct >= 40:
        level = "partial"
    elif pct > 0:
        level = "weak"
    else:
        level = "none"

    return {
        "coverage_pct":   pct,
        "required_count": len(required),
        "matched_count":  len(matched),
        "matched":        matched,
        "missing":        missing,
        "level":          level,
    }


def batch_coverage(profile: dict, jobs: list) -> list:
    """Attach 'coverage_pct' + 'coverage_level' + matched/missing to each job."""
    profile_skills = profile.get("summary", {}).get("all_skills", []) or _get_skills(profile)
    for job in jobs:
        cov = coverage_score(profile_skills, job)
        job["coverage_pct"]     = cov["coverage_pct"]
        job["coverage_level"]   = cov["level"]
        job["coverage_matched"] = cov["matched"]
        job["coverage_missing"] = cov["missing"]
    return jobs


# ── Core score functions ────────────────────────────────────────────────────

def compute_score(profile: dict, job: dict) -> float:
    """Score a single job. For many jobs use batch_score (much faster)."""
    job_clean = _build_job_text(job)
    if not job_clean:
        return 0.0
    profile_clean = _build_profile_text(profile)
    all_skills = profile.get("summary", {}).get("all_skills", []) or _get_skills(profile)
    prominent = _get_prominent_skills(profile)

    cosine_raw    = _cosine_score(profile_clean, job_clean)
    length_factor = _description_length_factor(job_clean)
    cosine        = cosine_raw * length_factor

    skill = _skill_overlap_score(all_skills, job_clean, prominent)
    edu   = _education_score(profile, job_clean)
    yr    = _year_of_study_score(profile, job_clean)

    raw_pct = (W_COSINE * cosine + W_SKILL * skill
               + W_EDUCATION * edu + W_YEAR * yr) * 100
    return round(_calibrate_score(raw_pct), 2)


def batch_score(profile: dict, jobs: list) -> list:
    """
    Score N jobs in one shot. Fits TF-IDF ONCE for all jobs — ~300x faster
    than calling compute_score() N times, and uses ~5x less memory.
    Critical for avoiding OOM on Render free tier.
    """
    if not jobs:
        return []
    profile_clean = _build_profile_text(profile)
    all_skills = profile.get("summary", {}).get("all_skills", []) or _get_skills(profile)
    prominent = _get_prominent_skills(profile)

    job_texts = [_build_job_text(j) for j in jobs]
    length_factors = [_description_length_factor(t) for t in job_texts]

    cosines = [0.0] * len(jobs)
    if SKLEARN_AVAILABLE and profile_clean:
        try:
            vectorizer = TfidfVectorizer(
                ngram_range=(1, 2), max_features=5000,
                sublinear_tf=True, dtype=np.float32,
            )
            corpus = [profile_clean] + job_texts
            matrix = vectorizer.fit_transform(corpus)
            sims = cosine_similarity(matrix[0:1], matrix[1:])[0]
            cosines = [float(x) for x in sims]
        except Exception as e:
            logger.warning("batch TF-IDF failed, per-job fallback: %s", e)
            cosines = [_cosine_score(profile_clean, t) for t in job_texts]

    for job, job_clean, cos_raw, lf in zip(jobs, job_texts, cosines, length_factors):
        if not job_clean:
            job["match_score"] = 0.0
            continue
        cos = cos_raw * lf
        skill = _skill_overlap_score(all_skills, job_clean, prominent)
        edu   = _education_score(profile, job_clean)
        yr    = _year_of_study_score(profile, job_clean)
        raw_pct = (W_COSINE * cos + W_SKILL * skill
                   + W_EDUCATION * edu + W_YEAR * yr) * 100
        job["match_score"] = round(_calibrate_score(raw_pct), 2)

    return sorted(jobs, key=lambda j: j.get("match_score", 0), reverse=True)


def batch_score_and_coverage(profile: dict, jobs: list) -> list:
    """
    One-shot: compute both match_score AND coverage for every job.
    Use this in your pipeline.
    """
    scored = batch_score(profile, jobs)
    return batch_coverage(profile, scored)


# ── Score explainer ─────────────────────────────────────────────────────────

def explain_score(profile: dict, job: dict) -> dict:
    """
    Breakdown of why a job got its score. Used by /api/explain-score endpoint.
    """
    job_clean = _build_job_text(job)
    profile_clean = _build_profile_text(profile)
    all_skills = profile.get("summary", {}).get("all_skills", []) or _get_skills(profile)
    prominent = _get_prominent_skills(profile)

    matched = []
    for s in all_skills:
        count = _count_skill_mentions(s, job_clean)
        if count > 0:
            matched.append({
                "skill": s, "mentions": count,
                "prominent": s.lower() in prominent,
            })
    missing = [s for s in all_skills if not any(m["skill"] == s for m in matched)]

    cosine_raw = _cosine_score(profile_clean, job_clean)
    length_factor = _description_length_factor(job_clean)
    cosine = cosine_raw * length_factor
    skill = _skill_overlap_score(all_skills, job_clean, prominent)
    edu = _education_score(profile, job_clean)
    yr = _year_of_study_score(profile, job_clean)
    raw_pct = (W_COSINE * cosine + W_SKILL * skill + W_EDUCATION * edu + W_YEAR * yr) * 100
    total = round(_calibrate_score(raw_pct), 2)

    # Coverage
    cov = coverage_score(all_skills, job)

    return {
        "total_score":        total,
        "cosine_score":       round(cosine * 100, 1),
        "skill_score":        round(skill * 100, 1),
        "education_score":    round(edu * 100, 1),
        "year_score":         round(yr * 100, 1),
        "description_factor": round(length_factor, 2),
        "matched_skills":     matched,
        "missing_skills":     missing[:15],
        "skill_overlap":      f"{len(matched)}/{len(all_skills)}",
        "word_count":         len(job_clean.split()),
        "coverage":           cov,
    }


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample_profile = {
        "name": "Rushikesh Baban Kedar",
        "skills": ['c', 'colab', 'computer vision', 'data analysis', 'data visualisation',
                   'deep learning', 'git', 'github', 'gradio', 'imbalanced-learn', 'java',
                   'jupyter', 'machine learning', 'matplotlib', 'mongodb', 'mysql', 'nlp',
                   'numpy', 'pandas', 'plotly', 'python', 'scikit-learn', 'seaborn', 'shap',
                   'smote', 'statsmodels', 'transformers', 'xgboost'],
        "skills_explicit": ['python', 'pandas', 'xgboost', 'scikit-learn', 'machine learning',
                            'deep learning', 'nlp'],
        "education": [{"institution": "MITAOE Pune", "degree": "BTECH", "year": 2027}],
        "year_of_study": 3,
        "projects": [],
        "summary": {"all_skills": ['c', 'colab', 'computer vision', 'data analysis',
                                    'deep learning', 'machine learning', 'nlp', 'numpy',
                                    'pandas', 'python', 'scikit-learn', 'xgboost']},
    }
    sample_jobs = [
        {"title": "Artificial Intelligence (AI)", "company": "Assetcues",
         "description": "AI Intern. Build, test, optimize AI-driven solutions. Implement ML models for NLP or Computer Vision. Python scikit-learn. B.Tech student."},
        {"title": "Machine Learning", "company": "Symonis",
         "description": "ML intern proficient in Python, data analytics, data science, NLP, deep learning. Develop ML algorithms."},
        {"title": "Data Science Intern", "company": "SkillFied", "description": ""},
        {"title": "Frontend Developer", "company": "WebCo",
         "description": "Skills required: React, TypeScript, CSS, HTML, Redux, Jest. 2+ years experience."},
        {"title": "Sales Executive", "company": "ABC Corp",
         "description": "Sales executive for fmcg. 2-3 years field sales experience required."},
    ]

    print("── MATCH + COVERAGE ──")
    scored = batch_score_and_coverage(sample_profile, sample_jobs)
    print(f"{'Match':>6}  {'Cover':>6}  {'Level':<10}  {'Title':<40}")
    print("-" * 80)
    for j in scored:
        print(f"{j['match_score']:>6.1f}  {j['coverage_pct']:>5.1f}%  "
              f"{j['coverage_level']:<10}  {j['title'][:40]:<40}")
    print()

    print("── EXPLAIN: top job ──")
    print(json.dumps(explain_score(sample_profile, scored[0]), indent=2, default=str))
