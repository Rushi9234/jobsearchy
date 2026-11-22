"""
utils/joby_copilot.py — Joby AI Career Copilot for JobSearchy.

Provides intelligent, personalized career mentorship:
  - Connects to Groq (Llama-3.3-70B) if GROQ_API_KEY is present
  - Connects to Google Gemini (2.0-Flash) if GEMINI_API_KEY is present
  - Provides rich, context-aware offline responses with real user data if no API key is set
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]


def _build_system_prompt(profile: Dict[str, Any], top_jobs: List[Dict[str, Any]], career_gps: Dict[str, Any]) -> str:
    name = profile.get("name") or "Candidate"
    college = profile.get("college") or "Engineering College"
    course = profile.get("current_course") or "Tech Degree"
    skills = profile.get("skills") or []
    top_skills_str = ", ".join(skills[:12]) if skills else "Python, Web Development"
    
    jobs_summary = ""
    for j in top_jobs[:3]:
        title = j.get("title", "Role")
        company = j.get("company", "Company")
        score = j.get("match_score") or j.get("score") or 0
        jobs_summary += f"- {title} at {company} ({round(score)}% match)\n"

    gaps = [g.get("name") for g in career_gps.get("skill_gaps", [])[:4]]
    gaps_str = ", ".join(gaps) if gaps else "Docker, Cloud Deployment"
    recommended_role = career_gps.get("recommended_role") or "Data Analyst / AI Developer"
    readiness = career_gps.get("readiness_score", 80)

    return f"""You are Joby, the sharp, encouraging, and highly practical AI Career Copilot for JobSearchy.
You are chatting directly with {name}, an ambitious student/fresher from {college} studying {course}.

CANDIDATE CONTEXT:
- Name: {name}
- Extracted Skills ({len(skills)} total): {top_skills_str}
- Top Recommended Role: {recommended_role} (Readiness: {readiness}%)
- Top Active Jobs in Database:
{jobs_summary or "Active listings from PMIS, Jobicy, and Internshala available."}
- Top Priority Skill Gaps: {gaps_str}

BEHAVIOR GUIDELINES:
1. Always address {name} warmly and conversationally.
2. Provide concrete, actionable, BS-free advice tailored to Indian tech hiring and PMIS government schemes.
3. Suggest practical projects to bridge skill gaps ({gaps_str}).
4. Keep responses structured, concise, and easy to read (use short bullet points).
5. If asked about jobs or resume, cite specific details from their profile and active job matches.
"""


def _chat_with_groq(messages: List[Dict[str, str]], api_key: str) -> Optional[str]:
    """Chat completion via Groq API across active models."""
    import requests

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    for model in GROQ_MODELS:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": 800,
        }
        try:
            resp = requests.post(GROQ_ENDPOINT, headers=headers, json=payload, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[Joby Groq] Generated reply using {model}")
                return data["choices"][0]["message"]["content"].strip()
            elif resp.status_code in (404, 400, 429):
                logger.info(f"[Joby Groq] Model {model} status {resp.status_code}. Trying next model...")
                continue
            else:
                logger.warning("[Joby Groq] API status %d: %s", resp.status_code, resp.text[:200])
        except requests.exceptions.Timeout:
            logger.info(f"[Joby Groq] Model {model} timed out after 5s. Trying next...")
            continue
        except Exception as e:
            logger.warning("[Joby Groq] Model %s failed: %s", model, e)
            continue

    return None


def _chat_with_gemini(system_prompt: str, user_message: str, api_key: str) -> Optional[str]:
    """Chat completion via Google Gemini across active models."""
    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=api_key.strip())
        prompt = f"{system_prompt}\n\nUser Question:\n{user_message}"

        for model in GEMINI_MODELS:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.5,
                        max_output_tokens=800,
                    ),
                )
                logger.info(f"[Joby Gemini] Generated reply using {model}")
                return response.text.strip()
            except Exception as e:
                logger.info(f"[Joby Gemini] Model {model} failed: {e}. Trying next...")
                continue
        return None
    except Exception as e:
        logger.warning("[Joby Gemini] Request failed: %s", e)
        return None


def _smart_offline_reply(message: str, profile: Dict[str, Any], top_jobs: List[Dict[str, Any]], career_gps: Dict[str, Any]) -> str:
    """
    Intelligent context-aware offline assistant when no API keys are provided.
    Never fails or gives a generic placeholder.
    """
    msg = message.strip().lower()
    name = (profile.get("name") or "there").split()[0]
    skills = profile.get("skills") or []
    top_role = career_gps.get("recommended_role") or "Data Analyst / AI Developer"
    gaps = [g.get("name") for g in career_gps.get("skill_gaps", [])[:3]]
    gaps_str = ", ".join(gaps) if gaps else "Docker, AWS Deployment, and Power BI"

    # 1. Quick Action: Analyze Resume
    if "analyze resume" in msg or "resume review" in msg:
        return (
            f"Hey {name}, here is my instant diagnostic of your resume:\n\n"
            f"• **Strengths**: We detected **{len(skills)} relevant technical skills**, with strong foundations in {', '.join(skills[:4]).title()}.\n"
            f"• **Best Fit**: Your profile matches best with **{top_role}** roles.\n"
            f"• **ATS Optimization**: Ensure each project bullet uses the **Action + Context + Metric** formula (e.g. *'Engineered REST APIs using FastAPI, decreasing query latency by 28%'*).\n"
            f"• **Next Step**: Apply to jobs above 70% match first before broadening your search."
        )

    # 2. Quick Action: Find Matching Jobs
    if "find matching" in msg or "matching jobs" in msg or "best jobs" in msg:
        if top_jobs:
            job_list = "\n".join([
                f"• **{j.get('title')}** at *{j.get('company')}* ({round(j.get('match_score', 0))}% match) — [View Job]({j.get('url')})"
                for j in top_jobs[:3]
            ])
            return (
                f"Here are your highest-probability matches right now, {name}:\n\n"
                f"{job_list}\n\n"
                f"**Tip**: Tailor your headline to mention `{', '.join(skills[:3]).title()}` before applying."
            )
        return (
            f"I recommend exploring the **Jobs** tab with the 'High Match (65%+)' filter active. "
            f"Your skills in {', '.join(skills[:3]).title()} position you well for junior developer and analyst openings."
        )

    # 3. Quick Action: Show Skill Gaps
    if "skill gap" in msg or "gaps" in msg:
        return (
            f"Based on active employer listings, here are your top 3 skill gaps, {name}:\n\n"
            f"1. **{gaps[0] if len(gaps) > 0 else 'Docker'}**: Required in multiple junior and backend job descriptions.\n"
            f"2. **{gaps[1] if len(gaps) > 1 else 'Cloud Deployment (AWS/Render)'}**: Knowing how to deploy apps sets you apart from 80% of freshers.\n"
            f"3. **{gaps[2] if len(gaps) > 2 else 'Advanced SQL'}**: Essential for data analyst and backend screening tests.\n\n"
            f"**Action**: Pick one gap and build a mini proof-of-work project this week to immediately boost your match score."
        )

    # 4. Quick Action: Prepare Interview
    if "interview" in msg or "prepare interview" in msg:
        return (
            f"Here are 4 high-yield interview questions tailored for your target track (**{top_role}**):\n\n"
            f"1. **Architecture**: *'Walk me through the database schema and API structure of your most complex project.'*\n"
            f"2. **Technical Deep-Dive**: *'How do you handle pagination, error handling, and performance bottlenecks in Python APIs?'*\n"
            f"3. **SQL / Data**: *'What is the difference between WHERE and HAVING, and how do database indexes work under the hood?'*\n"
            f"4. **Problem Solving**: *'Tell me about a difficult bug you encountered during development and how you solved it.'*\n\n"
            f"Practice answering each using the **STAR** method (Situation, Task, Action, Result)."
        )

    # 5. Quick Action: Improve Resume
    if "improve resume" in msg:
        return (
            f"Here are 3 high-impact resume improvements for {name}:\n\n"
            f"1. **Lead with Proof**: Link your GitHub repo and live deployed URLs directly in your project header.\n"
            f"2. **Quantify Results**: Instead of *'Built a web scraper'*, write *'Built an automated multi-portal scraper processing 200+ listings daily with MD5 deduplication.'*\n"
            f"3. **Targeted Keywords**: Front-load your skill section with tools demanded by employers: {gaps_str}."
        )

    # 6. PMIS Government Internship query
    if "pmis" in msg or "government" in msg or "aicte" in msg or "stipend" in msg:
        return (
            f"The **PM Internship Scheme (PMIS)** is a massive opportunity for students and freshers:\n\n"
            f"• **Stipend**: ₹5,000/month direct bank transfer (DBT) from the government + ₹6,000 one-time grant.\n"
            f"• **Partners**: Top 500 Indian companies (TCS, L&T, Reliance, Mahindra, HDFC, etc.).\n"
            f"• **Application**: Verified through the official portal (`pminternship.mca.gov.in`).\n"
            f"Check the Government & PMIS filter in JobSearchy to see currently available corporate openings."
        )

    # 7. General Career Guidance fallback
    return (
        f"Hi {name}! As your JobSearchy Copilot, I'm analyzing your profile for **{top_role}**.\n\n"
        f"You have a great technical foundation with {len(skills)} skills including {', '.join(skills[:3]).title()}. "
        f"To stand out in the current Indian tech market:\n"
        f"• Apply to 5–8 high-match jobs weekly rather than mass applying.\n"
        f"• Build real deployed projects rather than tutorial clones.\n"
        f"• Address your top skill gaps: **{gaps_str}**.\n\n"
        f"Feel free to ask me to analyze your resume, prepare interview questions, or explain any job match score!"
    )


def generate_joby_reply(
    message: str,
    history: Optional[List[Dict[str, str]]] = None,
    profile: Optional[Dict[str, Any]] = None,
    top_jobs: Optional[List[Dict[str, Any]]] = None,
    career_gps: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Main entry point for Joby Copilot.
    Tries Groq -> Gemini -> Smart Contextual Fallback.
    Returns: {"reply": str, "model": str, "status": "success"}
    """
    if profile is None:
        profile = {}
    if top_jobs is None:
        top_jobs = []
    if career_gps is None:
        career_gps = {}
    if history is None:
        history = []

    sys_prompt = _build_system_prompt(profile, top_jobs, career_gps)

    # 1. Try Groq (Ultra-fast Llama-3.3-70B)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        messages = [{"role": "system", "content": sys_prompt}]
        for h in history[-4:]:
            role = "assistant" if h.get("sender") == "joby" else "user"
            messages.append({"role": role, "content": h.get("text", "")})
        messages.append({"role": "user", "content": message})
        
        reply = _chat_with_groq(messages, groq_key)
        if reply:
            return {"reply": reply, "model": "groq-llama-3.3-70b", "status": "success"}

    # 2. Try Gemini 2.0 Flash
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        reply = _chat_with_gemini(sys_prompt, message, gemini_key)
        if reply:
            return {"reply": reply, "model": "gemini-2.0-flash", "status": "success"}

    # 3. Smart Contextual Offline Rules Engine
    reply = _smart_offline_reply(message, profile, top_jobs, career_gps)
    return {"reply": reply, "model": "joby-smart-engine", "status": "success"}
