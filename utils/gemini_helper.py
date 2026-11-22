"""
utils/gemini_helper.py — Google Gemini API integration for JobSearchy

Provides AI-generated content for:
  - Flashcards (short, ~150 words): quick recruiter-term recall
  - Deep dives (long, ~500 words):  GeeksforGeeks-style documentation
  - Gap reasons (short):            "Why this skill matters + how many jobs need it"
  - Score explainers:                Plain-English why-this-scored-this

All responses are cached in SQLite so each skill costs at most ONE API call
globally, forever. Subsequent requests for the same skill are instant and free.

Setup:
  1. Get API key: https://aistudio.google.com/app/apikey
  2. Set env var: GEMINI_API_KEY=AIzaSy...
  3. pip install google-genai
"""

import os
import json
import sqlite3
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("google-genai not installed. Run: pip install google-genai")

MODELS = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]
MODEL = MODELS[0]
DB_PATH = "searchy.db"

# ── Client (singleton, lazy-loaded) ──────────────────────────────────────────
_client = None

def _get_client():
    global _client
    if _client is not None:
        return _client
    if not GEMINI_AVAILABLE:
        return None
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY not set — AI content disabled.")
        return None
    try:
        _client = genai.Client(api_key=api_key)
        return _client
    except Exception as e:
        logger.error("Failed to init Gemini client: %s", e)
        return None


# ── SQLite cache table ───────────────────────────────────────────────────────
def _init_cache_table():
    """Create the cache table if it doesn't exist. Idempotent."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS skill_content_cache (
            cache_key    TEXT PRIMARY KEY,
            skill        TEXT NOT NULL,
            content_type TEXT NOT NULL,
            content      TEXT NOT NULL,
            created_at   REAL NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cache_skill ON skill_content_cache(skill)")
    conn.commit()
    conn.close()


def _cache_key(skill: str, content_type: str) -> str:
    return f"{skill.lower().strip()}::{content_type}"


def _cache_get(skill: str, content_type: str) -> Optional[str]:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM skill_content_cache WHERE cache_key = ?",
            (_cache_key(skill, content_type),),
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        _init_cache_table()
        return None


def _cache_set(skill: str, content_type: str, content: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO skill_content_cache
               (cache_key, skill, content_type, content, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (_cache_key(skill, content_type), skill.lower().strip(),
             content_type, content, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Cache write failed for %s: %s", skill, e)


# ── Prompts ──────────────────────────────────────────────────────────────────
PROMPTS = {
    "flashcard": """You are writing a tech skill flashcard for an Indian engineering student preparing for interviews.
Skill: {skill}

Write a flashcard in this EXACT JSON format (and NOTHING else, no markdown fences):
{{
  "term": "{skill}",
  "short_definition": "One sentence, under 20 words.",
  "why_recruiters_care": "Two sentences explaining why companies hiring in 2026 actively look for this skill.",
  "real_example": "One concrete example of how it's used in industry. Be specific — name a use-case, dataset, or company.",
  "pro_tip": "One tip for a student to mention this skill in interviews convincingly."
}}

Keep the whole response under 150 words combined. Be direct. No fluff.""",

    "deep_dive": """You are writing a GeeksforGeeks-style technical documentation page for an Indian engineering student.
Skill: {skill}

Write a comprehensive but readable 400-500 word guide in this EXACT JSON format (no markdown fences):
{{
  "term": "{skill}",
  "overview": "2-3 sentences defining the skill and its category.",
  "how_it_works": "3-4 sentences on the core concept, key idea, or algorithm. Use analogies if helpful.",
  "key_concepts": ["concept 1", "concept 2", "concept 3", "concept 4", "concept 5"],
  "common_use_cases": ["use case 1 with company/industry", "use case 2", "use case 3"],
  "code_snippet": "A 5-10 line Python or relevant-language code example that's pedagogical, not production. Use triple newlines between lines. No comments inside strings.",
  "prerequisites": ["prereq 1", "prereq 2", "prereq 3"],
  "learning_path": ["Step 1 — start here", "Step 2 — next", "Step 3 — intermediate", "Step 4 — advanced"],
  "interview_questions": ["question 1", "question 2", "question 3"],
  "pitfalls": "2 sentences on common mistakes beginners make."
}}

Be technically accurate. No hype. Prefer concrete over abstract.""",

    "gap_reason": """A student's resume is MISSING the skill: {skill}
Context: They are a 3rd-year B.Tech CS student interested in AI/ML and Data Science internships.

Write a short persuasion card in this EXACT JSON format (no markdown fences):
{{
  "skill": "{skill}",
  "why_it_matters": "Two sentences explaining why this skill unlocks more/better jobs for this student.",
  "typical_demand": "One sentence: roughly what fraction of ML/DS internship listings mention this.",
  "learning_estimate": "Realistic time estimate for a motivated CS student to reach interview-ready (e.g. '2 weekends', '1 month of evenings').",
  "first_project": "One specific small project they can build in 1-2 days to claim this skill credibly on their resume."
}}

Keep total under 120 words. Be direct. Indian market context.""",

    "score_explain": """A student scored {score}/100 for the job "{title}" at {company}.
Matched skills: {matched}
Missing skills: {missing}

Write a 2-3 sentence plain-English explanation of WHY this score, that a student would find helpful.
Mention specifically which skills helped, which gaps hurt, and one concrete thing to address.
No JSON, just the prose paragraph. Under 60 words.""",
}


# ── Public API ───────────────────────────────────────────────────────────────
def get_skill_content(skill: str, content_type: str = "flashcard") -> Optional[dict]:
    """
    Get AI-generated content for a skill. Cached on first call.

    content_type: 'flashcard' | 'deep_dive' | 'gap_reason'
    Returns dict, or None on failure.
    """
    if not skill or not skill.strip():
        return None
    if content_type not in ("flashcard", "deep_dive", "gap_reason"):
        logger.error("Unknown content_type: %s", content_type)
        return None

    # 1. Check cache
    cached = _cache_get(skill, content_type)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            logger.warning("Cached content malformed for %s/%s — regenerating", skill, content_type)

    # 2. Generate via Gemini
    client = _get_client()
    if client is None:
        return _fallback_content(skill, content_type)

    prompt = PROMPTS[content_type].format(skill=skill)
    for model_name in MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=1500,
                    response_mime_type="application/json",
                ),
            )
            text = response.text.strip()
            # Strip markdown fences just in case
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            parsed = json.loads(text)
            # Cache it
            _cache_set(skill, content_type, json.dumps(parsed))
            return parsed
        except json.JSONDecodeError as e:
            logger.warning("Gemini returned malformed JSON for %s/%s: %s", skill, content_type, e)
            return _fallback_content(skill, content_type)
        except Exception as e:
            logger.info("Gemini model %s failed for %s: %s. Trying next model...", model_name, skill, e)
            continue

    return _fallback_content(skill, content_type)


def explain_score_prose(score: float, title: str, company: str,
                        matched: list, missing: list) -> str:
    """Returns a plain-English explanation of why a job got its score."""
    client = _get_client()
    if client is None:
        return _fallback_score_explain(score, matched, missing)

    prompt = PROMPTS["score_explain"].format(
        score=round(score, 1),
        title=title or "this role",
        company=company or "the company",
        matched=", ".join([m if isinstance(m, str) else m.get("skill", "") for m in matched[:5]]) or "none",
        missing=", ".join(missing[:5]) or "none",
    )
    for model_name in MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.5,
                    max_output_tokens=200,
                ),
            )
            return response.text.strip()
        except Exception as e:
            logger.info("score explain model %s failed: %s. Trying next...", model_name, e)
            continue
    return _fallback_score_explain(score, matched, missing)


# ── Fallbacks (used when Gemini is down or API key missing) ──────────────────
def _fallback_content(skill: str, content_type: str) -> dict:
    """Minimal usable content if API is unavailable."""
    if content_type == "flashcard":
        return {
            "term": skill,
            "short_definition": f"{skill} — a technical skill used in software / data engineering.",
            "why_recruiters_care": f"Companies often list {skill} in job descriptions. Knowing it at interview level puts you in the top candidate pool.",
            "real_example": f"Common in production systems that rely on {skill}.",
            "pro_tip": f"Be ready to talk about a project where you actually used {skill}.",
            "_fallback": True,
        }
    if content_type == "deep_dive":
        return {
            "term": skill,
            "overview": f"{skill} is a technology/skill used widely in modern software and data work.",
            "how_it_works": "Detailed documentation temporarily unavailable. Please check the official docs.",
            "key_concepts": [],
            "common_use_cases": [],
            "code_snippet": "# Detailed example unavailable",
            "prerequisites": [],
            "learning_path": [],
            "interview_questions": [],
            "pitfalls": "",
            "_fallback": True,
        }
    if content_type == "gap_reason":
        return {
            "skill": skill,
            "why_it_matters": f"{skill} is commonly requested in internship postings. Adding it typically increases matches.",
            "typical_demand": "Demand data unavailable — check the Analytics tab.",
            "learning_estimate": "Typically a few weekends to reach interview-ready.",
            "first_project": f"Build a small personal project using {skill} and publish it on GitHub.",
            "_fallback": True,
        }
    return {}


def _fallback_score_explain(score: float, matched: list, missing: list) -> str:
    matched_names = [m if isinstance(m, str) else m.get("skill", "") for m in matched[:3]]
    if score >= 75:
        verdict = "a strong match"
    elif score >= 55:
        verdict = "a decent match"
    else:
        verdict = "a weak match"
    msg = f"This is {verdict} at {round(score,0)}/100. "
    if matched_names:
        msg += f"Your skills in {', '.join(matched_names)} align well. "
    if missing:
        msg += f"Consider adding {missing[0]} to boost your fit."
    return msg


# ── Quick test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _init_cache_table()
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set — will use fallbacks")
    print("\n--- Flashcard for 'XGBoost' ---")
    print(json.dumps(get_skill_content("XGBoost", "flashcard"), indent=2))
    print("\n--- Gap reason for 'Docker' ---")
    print(json.dumps(get_skill_content("Docker", "gap_reason"), indent=2))
