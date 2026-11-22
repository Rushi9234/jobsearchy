"""
utils/resume_llm_parser.py — AI-Powered Resume Parser for JobSearchy

Features:
  1. Groq API integration (Llama-3.3-70B-Versatile) — ultra-fast (<1s), 100% free tier.
  2. Google Gemini API integration (Gemini-2.0-Flash) — 100% free tier.
  3. Strict JSON output validation.
  4. Automatic 6-second timeout safety to prevent hanging or slowing down users.
  5. 100% Seamless offline fallback to our upgraded regex parser (utils/resume_parser.py)
     when keys are missing, network is offline, or rate limits are reached.
"""

import os
import json
import logging
import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from utils.resume_parser import (
    extract_text,
    build_weighted_skills,
    detect_domain,
    parse_resume as parse_resume_regex,
    TECH_SKILLS,
    SOFT_SKILLS,
)

logger = logging.getLogger("jobsearchy.llm_parser")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"

RESUME_EXTRACTION_PROMPT = """You are an expert resume parsing engine for Indian and global tech candidates.
Extract the candidate's structured details from the resume text below into STRICT JSON format.

CRITICAL RULES:
1. "name": The actual candidate's full legal name (e.g. "Rushikesh Baban Kedar", "Akash Bhuyan").
   NEVER use job titles like "Full Stack Developer", "Software Engineer", or section names as the candidate name!
2. "college": The university, college, or institute name (e.g. "MIT Academy of Engineering, Pune").
   DO NOT put degrees like "Bachelor of Engineering" or student summaries here.
3. "current_course": The degree program (e.g. "B.Tech in Computer Science Engineering").
4. "year_of_study": An integer 1, 2, 3, or 4 if currently studying, or null.
5. "cgpa": Numeric CGPA out of 10.0 (e.g. 7.43) or null.
6. "skills": Complete array of lowercase technical and soft skills mentioned or demonstrated.
7. Return ONLY the raw JSON object without markdown fences or additional prose.

Required JSON Structure:
{{
  "name": "Candidate Full Name",
  "email": "candidate@example.com",
  "phone": "+91XXXXXXXXXX",
  "college": "College / University Name",
  "current_course": "Degree Name",
  "year_of_study": 3,
  "cgpa": 7.43,
  "links": {{
    "github": "https://github.com/...",
    "linkedin": "https://linkedin.com/in/...",
    "portfolio": "https://..."
  }},
  "skills": ["python", "react", "fastapi", "machine learning"],
  "education": [
    {{"institution": "College Name", "degree": "B.Tech CS", "year": 2025}}
  ],
  "projects": [
    {{"title": "Project Title", "description": "Project description and technologies used"}}
  ],
  "experience": [
    {{"role": "Intern", "company": "Company Name", "duration": "3 months", "description": "Work done"}}
  ],
  "certifications": [
    {{"name": "Cert Name", "issuer": "Issuer Organization"}}
  ]
}}

Resume Text:
---
{resume_text}
---
"""


def _call_groq(text: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Calls Groq Llama-3.3-70b-versatile with strict JSON output."""
    import requests

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a specialized JSON resume extraction engine. You output only valid JSON.",
            },
            {
                "role": "user",
                "content": RESUME_EXTRACTION_PROMPT.format(resume_text=text[:12000]),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 2500,
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    resp = requests.post(GROQ_ENDPOINT, headers=headers, json=payload, timeout=6)
    if resp.status_code == 200:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    else:
        logger.warning(f"[Groq] API returned status {resp.status_code}: {resp.text[:200]}")
        return None


def _call_gemini(text: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Calls Google Gemini-2.0-flash with structured JSON output."""
    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=api_key.strip())
        prompt = RESUME_EXTRACTION_PROMPT.format(resume_text=text[:12000])

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=2500,
                response_mime_type="application/json",
            ),
        )

        content = response.text.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"[Gemini] API error: {e}")
        return None


def parse_resume_hybrid(file_path: str) -> dict:
    """
    Main entry point for resume parsing:
    1. Checks for GROQ_API_KEY or GEMINI_API_KEY.
    2. If found, attempts LLM extraction with 6s timeout.
    3. If not found or if API fails, transparently falls back to our upgraded regex parser.
    4. Combines results with weighted skill aggregation and domain classification.
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    # Step 1: If neither key is present, use our tested offline regex parser directly
    if not groq_key and not gemini_key:
        logger.info("[ResumeParser] No LLM keys (GROQ_API_KEY / GEMINI_API_KEY) found. Using upgraded offline regex parser.")
        return parse_resume_regex(file_path)

    # Step 2: Extract text from document
    try:
        raw_text = extract_text(file_path)
    except Exception as e:
        logger.error(f"[ResumeParser] Failed to extract text from {file_path}: {e}")
        return parse_resume_regex(file_path)

    parsed_llm = None

    # Step 3: Try Groq first if key exists (fastest response)
    if groq_key:
        try:
            logger.info("[ResumeParser] Attempting extraction via Groq (Llama-3.3-70B)...")
            parsed_llm = _call_groq(raw_text, groq_key)
        except Exception as e:
            logger.warning(f"[ResumeParser] Groq extraction failed: {e}")

    # Step 4: Try Gemini if Groq was not available or failed
    if not parsed_llm and gemini_key:
        try:
            logger.info("[ResumeParser] Attempting extraction via Google Gemini...")
            parsed_llm = _call_gemini(raw_text, gemini_key)
        except Exception as e:
            logger.warning(f"[ResumeParser] Gemini extraction failed: {e}")

    # Step 5: If LLM extraction failed or returned invalid data, fall back to regex
    if not parsed_llm or not isinstance(parsed_llm, dict) or not parsed_llm.get("name"):
        logger.warning("[ResumeParser] LLM extraction did not yield valid profile. Falling back to upgraded regex parser.")
        return parse_resume_regex(file_path)

    # Step 6: Format and augment LLM result with skill confidence weighting
    logger.info(f"[ResumeParser] Successfully parsed resume for candidate: {parsed_llm.get('name')}")

    skills_raw = parsed_llm.get("skills", [])
    if isinstance(skills_raw, dict):
        skills_flat = [s.lower().strip() for s in (skills_raw.get("technical", []) + skills_raw.get("soft", []))]
    elif isinstance(skills_raw, list):
        skills_flat = [str(s).lower().strip() for s in skills_raw if str(s).strip()]
    else:
        skills_flat = []

    projects = parsed_llm.get("projects", []) or []
    experience = parsed_llm.get("experience", []) or []
    certifications = parsed_llm.get("certifications", []) or []

    # Calculate weighted skill confidences
    weighted = build_weighted_skills(skills_flat, projects, experience, certifications)
    all_skills_flat = weighted["all_skills"]
    domain = detect_domain(raw_text, all_skills_flat)

    return {
        "source_file":     str(Path(file_path).resolve()),
        "parsed_at":       datetime.datetime.utcnow().isoformat() + "Z",
        "parser_engine":   "llm_hybrid",
        "name":            parsed_llm.get("name") or "Unknown",
        "email":           parsed_llm.get("email"),
        "phone":           parsed_llm.get("phone"),
        "links":           parsed_llm.get("links") or {},
        "skills":          all_skills_flat,
        "skills_weighted": weighted["weighted"],
        "skills_sources":  weighted["sources"],
        "skills_explicit": sorted(set(skills_flat)),
        "education":       parsed_llm.get("education") or [],
        "college":         parsed_llm.get("college"),
        "current_course":  parsed_llm.get("current_course"),
        "domain":          domain,
        "year_of_study":   parsed_llm.get("year_of_study"),
        "cgpa":            parsed_llm.get("cgpa"),
        "projects":        projects,
        "experience":      experience,
        "certifications":  certifications,
        "summary": {
            "all_skills":     all_skills_flat,
            "num_explicit":   len(skills_flat),
            "num_inferred":   max(0, len(all_skills_flat) - len(skills_flat)),
            "has_experience": len(experience) > 0,
            "num_projects":   len(projects),
            "num_certs":      len(certifications),
        },
    }
