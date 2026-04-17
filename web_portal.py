import os
import sys
import json
import logging
import threading
import sqlite3
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.resume_parser import parse_resume
from utils.matcher import batch_score, batch_score_and_coverage, coverage_score, explain_score as matcher_explain
from utils.filters import filter_jobs
from database.db import (
    init_db, get_all_jobs, get_top_jobs, get_saved_jobs,
    toggle_saved, get_stats, insert_job, is_seen, mark_seen,
    get_tracker_entries, add_tracker_entry, update_tracker_stage, delete_tracker_entry
)
from scrapers.internshala_scraper import scrape as scrape_internshala
from scrapers.company_scraper import scrape_linkedin

# Gemini AI helper (optional — system works without it, just uses fallbacks)
try:
    from utils.gemini_helper import get_skill_content, explain_score_prose, _init_cache_table
    _init_cache_table()
    GEMINI_ENABLED = True
except Exception as e:
    print(f"[Gemini] Helper not available: {e}")
    GEMINI_ENABLED = False

logger = logging.getLogger("jobsearchy")
logging.basicConfig(level=logging.INFO)


def _safe_import(fn_name, module):
    try:
        import importlib
        mod = importlib.import_module(module)
        fn = getattr(mod, fn_name)
        print(f"[Scraper] Loaded {module}.{fn_name}")
        return fn
    except Exception as e:
        print(f"[Scraper] {module}.{fn_name} not available: {e}")
        return lambda **kwargs: []

scrape_unstop      = _safe_import('scrape_unstop',      'scrapers.unstop_scraper')
scrape_devfolio    = _safe_import('scrape_devfolio',    'scrapers.devfolio_scraper')
scrape_hackerearth = _safe_import('scrape_hackerearth', 'scrapers.hackerearth_scraper')
scrape_wellfound   = _safe_import('scrape_wellfound',   'scrapers.wellfound_scraper')
scrape_naukri      = _safe_import('scrape_naukri',      'scrapers.naukri_scraper')
scrape_govt        = _safe_import('scrape_govt_jobs',   'scrapers.govt_scraper')
from notifiers.email_notifier import send_daily_digest

app = Flask(__name__, static_folder="static", template_folder="static")

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "docx", "doc"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

init_db()

pipeline_status = {"running": False, "message": "Idle", "progress": 0}

# Tracks background rescoring so the frontend can poll if it wants
rescore_status = {"running": False, "done": 0, "total": 0, "message": "Idle"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def flatten_skills(skills):
    """Handle skills as list OR dict {technical:[...], soft:[...]}"""
    if not skills:
        return []
    if isinstance(skills, list):
        return skills
    if isinstance(skills, dict):
        return [s for v in skills.values() for s in (v if isinstance(v, list) else [v])]
    return []


def _rescore_all_jobs(profile: dict):
    """
    Rescore every job in DB against a new profile.

    NOTE: This is now called in a BACKGROUND THREAD (not inline) so it can't
    kill the gunicorn worker on slow/low-memory free tiers like Render.

    We also process jobs in batches of 500 to keep memory use bounded even
    when the DB grows to tens of thousands of rows.
    """
    global rescore_status
    BATCH_SIZE = 500

    try:
        conn = sqlite3.connect("searchy.db")
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM jobs")
        total = cur.fetchone()[0] or 0

        rescore_status = {"running": True, "done": 0, "total": total, "message": "Starting rescore..."}

        if total == 0:
            rescore_status = {"running": False, "done": 0, "total": 0, "message": "No jobs to rescore"}
            conn.close()
            return 0

        offset = 0
        rescored_count = 0
        while offset < total:
            cur.execute(
                "SELECT id, title, company, description, tags FROM jobs LIMIT ? OFFSET ?",
                (BATCH_SIZE, offset),
            )
            rows = cur.fetchall()
            if not rows:
                break

            job_list = []
            for jid, title, company, desc, tags in rows:
                try:
                    tag_list = json.loads(tags) if tags else []
                except Exception:
                    tag_list = []
                job_list.append({
                    "id":          jid,
                    "title":       title   or "",
                    "company":     company or "",
                    "description": desc    or "",
                    "tags":        tag_list,
                })

            scored = batch_score(profile, job_list)
            for job in scored:
                cur.execute(
                    "UPDATE jobs SET match_score=? WHERE id=?",
                    (job.get("match_score", 0), job["id"]),
                )
            conn.commit()

            rescored_count += len(scored)
            offset += BATCH_SIZE
            rescore_status = {
                "running": True,
                "done": rescored_count,
                "total": total,
                "message": f"Rescored {rescored_count}/{total}...",
            }

        conn.close()
        print(f"[Upload] Rescored {rescored_count} jobs for {profile.get('name')}")
        rescore_status = {
            "running": False,
            "done": rescored_count,
            "total": total,
            "message": f"Done — rescored {rescored_count} jobs.",
        }
        return rescored_count

    except Exception as e:
        print(f"[Upload] Rescore error: {e}")
        rescore_status = {"running": False, "done": 0, "total": 0, "message": f"Error: {e}"}
        return 0


# ── Serve frontend ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Upload resume ─────────────────────────────────────────────────────────────
@app.route("/api/upload-resume", methods=["POST"])
def upload_resume():
    """
    Parses the resume and saves profile.json synchronously (fast — under 5s).
    Rescoring is kicked off in a BACKGROUND THREAD so we return immediately
    and don't get killed by gunicorn's 30s timeout or Render's 512MB RAM cap.
    """
    if "resume" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["resume"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "PDF files only"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        profile = parse_resume(filepath)

        # Flatten skills to list if parser returned dict
        skills = profile.get("skills", [])
        if isinstance(skills, dict):
            flat = skills.get("technical", []) + skills.get("soft", [])
            profile["skills"] = flat
            profile.setdefault("summary", {})["all_skills"] = flat

        with open("profile.json", "w") as f:
            json.dump(profile, f, indent=2)

        # ── Kick off rescoring in the BACKGROUND (don't block the response) ──
        # This was the cause of the Render OOM + WORKER TIMEOUT crashes.
        if not rescore_status.get("running"):
            threading.Thread(
                target=_rescore_all_jobs,
                args=(profile,),
                daemon=True,
            ).start()

        return jsonify({
            "success":          True,
            "profile":          profile,
            "rescoring_started": True,
            "message":          "Resume parsed. Rescoring old jobs in background.",
        })
    except Exception as e:
        logger.exception("[upload-resume] failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/rescore-status", methods=["GET"])
def get_rescore_status():
    """Frontend can poll this if it wants to show a 'rescoring X/Y' indicator."""
    return jsonify(rescore_status)


# ── Get profile ───────────────────────────────────────────────────────────────
@app.route("/api/profile", methods=["GET"])
def get_profile():
    if not os.path.exists("profile.json"):
        return jsonify({"error": "No profile found"}), 404
    with open("profile.json") as f:
        return jsonify(json.load(f))


# ── Smart keyword builder for personalized scraping ──────────────────────────
DOMAIN_BOOSTERS = {
    "aiml":        ["machine learning", "deep learning", "ai intern", "ml engineer"],
    "datascience": ["data science", "data analyst", "python data", "analytics intern"],
    "webdev":      ["full stack", "frontend developer", "backend developer", "react intern"],
    "devops":      ["devops", "cloud engineer", "sre intern", "kubernetes"],
    "research":    ["research intern", "quantitative research", "data research"],
    "entc":        ["embedded", "electronics intern", "iot intern", "vlsi"],
}


def _build_personalized_keywords(profile: dict, max_keywords: int = 6) -> list:
    """
    Build scraping keywords tailored to this user's resume.

    Strategy:
      1. Start with top-confidence weighted skills (if v2 parser was used)
      2. Fall back to flat skills list
      3. Add domain-specific booster terms
      4. Deduplicate and cap
    """
    keywords = []

    # 1. Weighted skills (v2) — take the highest-confidence non-generic ones
    weighted = profile.get("weighted_skills") or []
    if weighted:
        # Skip very short/generic skills that make bad search terms
        BAD_QUERY_SKILLS = {"c", "r", "go", "ai", "ml", "nlp", "cv", "git", "api", "rest", "sql", "html", "css", "ui"}
        high_conf = [
            w["skill"] for w in weighted
            if w.get("confidence", 0) >= 0.75 and w["skill"].lower() not in BAD_QUERY_SKILLS
        ]
        keywords.extend(high_conf[:4])

    # 2. Fall back to flat skills list
    if not keywords:
        flat = flatten_skills(profile.get("skills", []))
        BAD = {"c", "r", "go", "git", "api"}
        keywords = [s for s in flat if s.lower() not in BAD and len(s) >= 3][:4]

    # 3. Add domain boosters
    domain = profile.get("domain", "datascience")
    boosters = DOMAIN_BOOSTERS.get(domain, DOMAIN_BOOSTERS["datascience"])
    for b in boosters[:2]:
        if b not in keywords:
            keywords.append(b)

    # 4. Hard fallback if still empty
    if not keywords:
        keywords = ["python", "data science", "machine learning"]

    # Dedup preserving order
    seen = set()
    out = []
    for k in keywords:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            out.append(k)
    return out[:max_keywords]



    global pipeline_status
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    def _watchdog():
        import time
        time.sleep(180)
        if pipeline_status.get("running"):
            pipeline_status["running"]  = False
            pipeline_status["message"]  = "Pipeline timed out — partial results saved."
            pipeline_status["progress"] = 100
            print("[Pipeline] Watchdog triggered — forced completion after 3 min")
    threading.Thread(target=_watchdog, daemon=True).start()

    pipeline_status = {"running": True, "message": "Loading profile...", "progress": 5}
    try:
        if not os.path.exists("profile.json"):
            pipeline_status = {"running": False, "message": "Upload resume first!", "progress": 0}
            return

        with open("profile.json") as f:
            profile = json.load(f)

        # ── Personalized keyword selection (v2) ────────────────────────────
        # Instead of hardcoded generics, build keywords from:
        #   1. User's top-confidence skills (from weighted_skills if available)
        #   2. User's detected domain → generic boosters for that domain
        #   3. Optional: user's saved jobs → infer preferred topics (future)
        keywords = _build_personalized_keywords(profile)
        print(f"[Pipeline] Personalized keywords for {profile.get('name', 'user')}: {keywords}")

        pipeline_status["message"]  = f"Searching for: {', '.join(keywords[:3])}..."
        pipeline_status["progress"] = 15

        scraper_configs = [
            ("Internshala", scrape_internshala, keywords,  "internship"),
            ("LinkedIn",    scrape_linkedin,    keywords,  "job"),
            ("Wellfound",   scrape_wellfound,   keywords,  "job"),
            ("Unstop",      scrape_unstop,      keywords,  "hackathon"),
            ("Devfolio",    scrape_devfolio,    keywords,  "hackathon"),
            ("HackerEarth", scrape_hackerearth, keywords,  "hackathon"),
            ("Naukri",      scrape_naukri,      keywords,  "job"),
            ("Govt",        lambda **kw: scrape_govt(), None, "internship"),
        ]

        all_jobs      = []
        scraper_results = {}
        progress_step = 40 / len(scraper_configs)

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_name = {
                executor.submit(_run_scraper, name, fn, kw, jtype): name
                for name, fn, kw, jtype in scraper_configs
            }
            completed = 0
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    jobs = future.result(timeout=20)
                    scraper_results[name] = len(jobs)
                    all_jobs.extend(jobs)
                    print(f"[Pipeline] {name}: {len(jobs)} jobs")
                except Exception as e:
                    scraper_results[name] = 0
                    print(f"[Pipeline] {name} failed: {e}")
                completed += 1
                pipeline_status["message"]  = f"Scraped {name} ({completed}/{len(scraper_configs)})..."
                pipeline_status["progress"] = int(15 + completed * progress_step)

        summary = " | ".join(f"{k}:{v}" for k, v in scraper_results.items())
        print(f"[Pipeline] Totals — {summary}")
        pipeline_status["message"]  = f"Found {len(all_jobs)} raw jobs across all sources..."
        pipeline_status["progress"] = 60

        pipeline_status["message"]  = f"Filtering & scoring {len(all_jobs)} jobs..."
        pipeline_status["progress"] = 65
        accepted, _ = filter_jobs(all_jobs)

        pipeline_status["message"]  = f"AI scoring + coverage for {len(accepted)} jobs..."
        pipeline_status["progress"] = 75
        result = batch_score_and_coverage(dict(profile), accepted)
        scored_jobs = result if (result and isinstance(result[0], dict)) else [
            {**job, "score": round(float(s), 2)} for job, s in zip(accepted, result)
        ]

        pipeline_status["message"]  = "Saving to database..."
        pipeline_status["progress"] = 90
        seen_this_run = set()
        new_count = 0
        for job in scored_jobs:
            job_id = job.get("job_id") or job.get("id", "")
            source = job.get("source", "")
            if not job_id or job_id in seen_this_run:
                continue
            seen_this_run.add(job_id)
            if "score" in job and "match_score" not in job:
                job["match_score"] = job["score"]
            if not is_seen(job_id, source):
                insert_job(job)
                mark_seen(job_id, source)
                new_count += 1

        pipeline_status = {
            "running":         False,
            "message":         f"Done! {new_count} new jobs added from {len([v for v in scraper_results.values() if v>0])}/8 sources.",
            "progress":        100,
            "scraper_results": scraper_results,
        }
    except Exception as e:
        import traceback
        pipeline_status = {"running": False, "message": f"Error: {str(e)}", "progress": 0}
        print(traceback.format_exc())


def run_pipeline_thread(days=7):
    """
    The actual background pipeline. Scrapes all sources in parallel,
    filters, scores (match + coverage), and saves new jobs.
    Personalizes search keywords based on the user's profile.
    """
    global pipeline_status
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time as _time

    def _watchdog():
        _time.sleep(180)
        if pipeline_status.get("running"):
            pipeline_status["running"]  = False
            pipeline_status["message"]  = "Pipeline timed out — partial results saved."
            pipeline_status["progress"] = 100
            print("[Pipeline] Watchdog triggered — forced completion after 3 min")
    threading.Thread(target=_watchdog, daemon=True).start()

    pipeline_status = {"running": True, "message": "Loading profile...", "progress": 5}
    try:
        if not os.path.exists("profile.json"):
            pipeline_status = {"running": False, "message": "Upload resume first!", "progress": 0}
            return

        with open("profile.json") as f:
            profile = json.load(f)

        # PERSONALIZED keywords from user's actual skills + domain
        keywords = _build_personalized_keywords(profile, max_keywords=6)
        print(f"[Pipeline] Using personalized keywords: {keywords}")

        pipeline_status["message"]  = f"Scraping 8 sources with: {', '.join(keywords[:3])}..."
        pipeline_status["progress"] = 15

        scraper_configs = [
            ("Internshala", scrape_internshala, keywords,  "internship"),
            ("LinkedIn",    scrape_linkedin,    keywords,  "job"),
            ("Wellfound",   scrape_wellfound,   keywords,  "job"),
            ("Unstop",      scrape_unstop,      keywords,  "hackathon"),
            ("Devfolio",    scrape_devfolio,    keywords,  "hackathon"),
            ("HackerEarth", scrape_hackerearth, keywords,  "hackathon"),
            ("Naukri",      scrape_naukri,      keywords,  "job"),
            ("Govt",        lambda **kw: scrape_govt(), None, "internship"),
        ]

        all_jobs = []
        scraper_results = {}
        progress_step = 40 / len(scraper_configs)

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_name = {
                executor.submit(_run_scraper, name, fn, kw, jtype): name
                for name, fn, kw, jtype in scraper_configs
            }
            completed = 0
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    jobs = future.result(timeout=20)
                    scraper_results[name] = len(jobs)
                    all_jobs.extend(jobs)
                    print(f"[Pipeline] {name}: {len(jobs)} jobs")
                except Exception as e:
                    scraper_results[name] = 0
                    print(f"[Pipeline] {name} failed: {e}")
                completed += 1
                pipeline_status["message"]  = f"Scraped {name} ({completed}/{len(scraper_configs)})..."
                pipeline_status["progress"] = int(15 + completed * progress_step)

        summary = " | ".join(f"{k}:{v}" for k, v in scraper_results.items())
        print(f"[Pipeline] Totals — {summary}")
        pipeline_status["message"]  = f"Found {len(all_jobs)} raw jobs across all sources..."
        pipeline_status["progress"] = 60

        pipeline_status["message"]  = f"Filtering {len(all_jobs)} jobs..."
        pipeline_status["progress"] = 65
        accepted, _ = filter_jobs(all_jobs)

        pipeline_status["message"]  = f"AI scoring + coverage for {len(accepted)} jobs..."
        pipeline_status["progress"] = 75
        result = batch_score_and_coverage(dict(profile), accepted)
        scored_jobs = result if (result and isinstance(result[0], dict)) else [
            {**job, "score": round(float(s), 2)} for job, s in zip(accepted, result)
        ]

        pipeline_status["message"]  = "Saving to database..."
        pipeline_status["progress"] = 90
        seen_this_run = set()
        new_count = 0
        for job in scored_jobs:
            job_id = job.get("job_id") or job.get("id", "")
            source = job.get("source", "")
            if not job_id or job_id in seen_this_run:
                continue
            seen_this_run.add(job_id)
            if "score" in job and "match_score" not in job:
                job["match_score"] = job["score"]
            if not is_seen(job_id, source):
                insert_job(job)
                mark_seen(job_id, source)
                new_count += 1

        sources_with_hits = len([v for v in scraper_results.values() if v > 0])
        pipeline_status = {
            "running":         False,
            "message":         f"Done! {new_count} new jobs added from {sources_with_hits}/8 sources.",
            "progress":        100,
            "scraper_results": scraper_results,
            "keywords_used":   keywords,
        }
    except Exception as e:
        import traceback
        pipeline_status = {"running": False, "message": f"Error: {str(e)}", "progress": 0}
        print(traceback.format_exc())


def _run_scraper(source_name, scraper_fn, keywords, default_job_type):
    try:
        try:
            jobs = scraper_fn(keywords=keywords)
        except TypeError:
            jobs = scraper_fn(keywords=keywords[:3] if keywords else [])
        for j in jobs:
            j.setdefault("job_type", default_job_type)
        return jobs
    except Exception as e:
        print(f"[{source_name}] scraper error: {e}")
        return []


@app.route("/api/run-pipeline", methods=["POST"])
def run_pipeline():
    if pipeline_status["running"]:
        return jsonify({"error": "Pipeline already running"}), 400
    data = request.get_json() or {}
    days = int(data.get("days", 7))
    thread = threading.Thread(target=run_pipeline_thread, args=(days,), daemon=True)
    thread.start()
    return jsonify({"success": True, "message": "Pipeline started"})


@app.route("/api/pipeline-status", methods=["GET"])
def get_pipeline_status():
    return jsonify(pipeline_status)


# ── Jobs API ──────────────────────────────────────────────────────────────────
@app.route("/api/jobs", methods=["GET"])
def get_jobs():
    limit     = request.args.get("limit",     100, type=int)
    min_score = request.args.get("min_score", 0,   type=int)
    source    = request.args.get("source",    "")
    search    = request.args.get("search",    "")

    jobs = get_all_jobs(limit=limit)

    for j in jobs:
        if "match_score" in j and "score" not in j:
            j["score"] = j["match_score"]
        if "job_type" not in j or not j.get("job_type"):
            src   = (j.get("source",  "") or "").lower()
            title = (j.get("title",   "") or "").lower()
            tags  = " ".join(j.get("tags", []) if isinstance(j.get("tags"), list) else [])
            combined = title + " " + src + " " + tags.lower()
            if any(s in src for s in ["unstop", "devfolio", "hackerearth"]) or \
               any(k in combined for k in ["hackathon", "challenge", "competition", "datathon", "ideathon", "sprint"]):
                j["job_type"] = "hackathon"
            elif any(s in src for s in ["govt_internshala", "govt_portal", "govt", "linkedin_govt",
                                         "niti_aayog", "mygov"]) or \
                 any(k in title for k in ["government", "niti aayog", "isro", "drdo", "aicte",
                                           "csir", "nabard", "nic", "meity", "dst", "rbi", "sebi"]):
                j["job_type"] = "govt"
            elif "internship" in title or "intern" in title or "internshala" in src or \
                 any(k in title for k in ["trainee", "apprentice"]):
                j["job_type"] = "internship"
            else:
                j["job_type"] = "job"

    job_type = request.args.get("job_type", "")
    if job_type and job_type != "all":
        jobs = [j for j in jobs if j.get("job_type", "") == job_type]

    if min_score > 0:
        jobs = [j for j in jobs if j.get("score", 0) >= min_score]
    if source:
        jobs = [j for j in jobs if source.lower() in (j.get("source", "") or "").lower()]
    if search:
        s = search.lower()
        jobs = [j for j in jobs if s in (j.get("title",   "") or "").lower()
                                or s in (j.get("company", "") or "").lower()]

    # ── Coverage score (Rushi's idea) — computed on-the-fly ─────────────────
    # If profile exists, compute what % of each job's required skills user has.
    # Cheap enough to do for <500 jobs; for larger lists, only compute top N.
    try:
        if os.path.exists("profile.json"):
            with open("profile.json") as f:
                profile = json.load(f)
            profile_skills = (
                profile.get("summary", {}).get("all_skills")
                or flatten_skills(profile.get("skills", []))
            )
            if profile_skills:
                # Only compute for first 200 jobs for speed
                for j in jobs[:200]:
                    cov = coverage_score(profile_skills, j)
                    j["coverage_pct"]   = cov["coverage_pct"]
                    j["coverage_level"] = cov["level"]
                    j["coverage_matched"] = cov["matched"]
                    j["coverage_missing"] = cov["missing"]
    except Exception as e:
        logger.warning("[api/jobs] coverage computation failed: %s", e)

    # Coverage filter — "show only jobs I can apply to with confidence"
    min_cov = request.args.get("min_coverage", 0, type=int)
    if min_cov > 0:
        jobs = [j for j in jobs if j.get("coverage_pct", 0) >= min_cov]

    return jsonify(jobs)


@app.route("/api/jobs/<int:job_id>/coverage", methods=["GET"])
def get_job_coverage(job_id):
    """Get coverage score for a single job."""
    if not os.path.exists("profile.json"):
        return jsonify({"error": "No profile"}), 400
    with open("profile.json") as f:
        profile = json.load(f)
    profile_skills = (
        profile.get("summary", {}).get("all_skills")
        or flatten_skills(profile.get("skills", []))
    )
    jobs = get_all_jobs(limit=100000)
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(coverage_score(profile_skills, job))


@app.route("/api/jobs/top", methods=["GET"])
def get_top():
    limit = request.args.get("limit", 20, type=int)
    return jsonify(get_top_jobs(limit=limit))


@app.route("/api/jobs/saved", methods=["GET"])
def get_saved():
    return jsonify(get_saved_jobs())


@app.route("/api/jobs/<int:job_id>/save", methods=["POST"])
def save_job(job_id):
    jobs = get_all_jobs(limit=100000)
    job  = next((j for j in jobs if j.get("id") == job_id), None)
    currently_saved = job.get("is_saved", False) if job else False
    toggle_saved(job_id, not currently_saved)
    return jsonify({"success": True, "saved": not currently_saved})


# ── Stats API ─────────────────────────────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def get_statistics():
    return jsonify(get_stats())


# ── Send email digest ─────────────────────────────────────────────────────────
@app.route("/api/send-digest", methods=["POST"])
def send_digest():
    try:
        data            = request.get_json() or {}
        recipient_email = data.get("email", "").strip()
        jobs            = get_top_jobs(limit=50)

        profile_data = {}
        if os.path.exists("profile.json"):
            with open("profile.json") as f:
                profile_data = json.load(f)

        user_name  = profile_data.get("name", "there")
        all_skills = profile_data.get("summary", {}).get("all_skills", []) or \
                     flatten_skills(profile_data.get("skills", []))

        # Use provided email or fallback to profile email then env var
        to_email = recipient_email or profile_data.get("email") or os.getenv("MAIL_TO", "")
        if not to_email:
            return jsonify({"error": "No recipient email. Please enter your email address."}), 400

        result = send_daily_digest(
            jobs,
            recipient_email=to_email,
            user_name=user_name,
            all_skills=all_skills,
        )
        if result:
            return jsonify({"success": True, "message": f"Email sent to {to_email}!"})
        else:
            return jsonify({"error": "Email failed — check MAIL_FROM/MAIL_PASS in Render environment variables."}), 500
    except Exception as e:
        logger.exception("[send-digest] failed")
        return jsonify({"error": str(e)}), 500


# ── Application Tracker API ───────────────────────────────────────────────────
@app.route("/api/tracker", methods=["GET"])
def get_tracker():
    return jsonify(get_tracker_entries())

@app.route("/api/tracker", methods=["POST"])
def create_tracker():
    data = request.get_json() or {}
    if not data.get("company") or not data.get("role"):
        return jsonify({"error": "company and role required"}), 400
    entry_id = add_tracker_entry(
        company=data["company"], role=data["role"],
        url=data.get("url", ""), stage=data.get("stage", "Applied"),
        note=data.get("note", "")
    )
    return jsonify({"success": True, "id": entry_id})

@app.route("/api/tracker/<int:entry_id>", methods=["PATCH"])
def update_tracker(entry_id):
    data  = request.get_json() or {}
    stage = data.get("stage")
    if not stage:
        return jsonify({"error": "stage required"}), 400
    update_tracker_stage(entry_id, stage)
    return jsonify({"success": True})

@app.route("/api/tracker/<int:entry_id>", methods=["DELETE"])
def delete_tracker(entry_id):
    delete_tracker_entry(entry_id)
    return jsonify({"success": True})


# ── WhatsApp share ────────────────────────────────────────────────────────────
@app.route("/api/whatsapp-share", methods=["POST"])
def whatsapp_share():
    data  = request.get_json() or {}
    phone = data.get("phone", "").strip().replace(" ", "").replace("-", "")
    jobs  = get_top_jobs(limit=5)
    if not jobs:
        return jsonify({"error": "No top jobs to share"}), 400

    lines = ["🔍 *JobSearchy — Your Top Job Matches*\n"]
    for i, j in enumerate(jobs, 1):
        score = j.get("match_score", 0)
        lines.append(
            f"*{i}. {j.get('title','?')}*\n"
            f"🏢 {j.get('company','?')} | 📍 {j.get('location','?')}\n"
            f"💯 Match: {score:.0f}/100\n"
            f"🔗 {j.get('url','')}\n"
        )
    lines.append("_Sent by JobSearchy — AI Job Discovery_")
    text = "\n".join(lines)

    import urllib.parse
    encoded = urllib.parse.quote(text)
    wa_url  = f"https://wa.me/{phone}?text={encoded}" if phone else f"https://wa.me/?text={encoded}"
    return jsonify({"success": True, "url": wa_url})


# ── Pipeline reset ────────────────────────────────────────────────────────────
@app.route("/api/pipeline-reset", methods=["POST"])
def pipeline_reset():
    global pipeline_status
    pipeline_status = {"running": False, "message": "Reset by user.", "progress": 0}
    return jsonify({"success": True})


# ── AI Skill Content API (Gemini-powered) ─────────────────────────────────────
@app.route("/api/skill-content", methods=["GET"])
def skill_content():
    """
    Get AI-generated content for a skill.
    Query params:
      skill        — the skill name (required)
      content_type — 'flashcard' | 'deep_dive' | 'gap_reason' (default: flashcard)
    Response is cached in SQLite — same skill only costs 1 API call globally.
    """
    skill = (request.args.get("skill") or "").strip()
    content_type = request.args.get("content_type", "flashcard")
    if not skill:
        return jsonify({"error": "skill query param required"}), 400
    if not GEMINI_ENABLED:
        return jsonify({"error": "Gemini helper not available"}), 503

    content = get_skill_content(skill, content_type)
    if content is None:
        return jsonify({"error": "Could not generate content"}), 500
    return jsonify({"skill": skill, "content_type": content_type, "content": content})


@app.route("/api/flashcards-for-profile", methods=["GET"])
def flashcards_for_profile():
    """
    Returns flashcards for every skill in the user's profile.
    Each flashcard is cached, so repeat calls are instant and free.
    """
    if not os.path.exists("profile.json"):
        return jsonify({"error": "No profile. Upload resume first."}), 400
    if not GEMINI_ENABLED:
        return jsonify({"error": "Gemini helper not available"}), 503

    with open("profile.json") as f:
        profile = json.load(f)
    skills = flatten_skills(profile.get("skills", []))
    limit = int(request.args.get("limit", 15))
    skills = skills[:limit]

    cards = []
    for s in skills:
        content = get_skill_content(s, "flashcard")
        if content:
            cards.append({"skill": s, "card": content})
    return jsonify({"cards": cards, "total": len(cards)})


# ── Score explainer ──────────────────────────────────────────────────────────
@app.route("/api/explain-score/<int:job_id>", methods=["GET"])
def explain_job_score(job_id):
    """
    Returns a detailed breakdown of why a specific job got its match score,
    plus an AI-generated plain-English explanation.
    """
    if not os.path.exists("profile.json"):
        return jsonify({"error": "No profile"}), 400
    with open("profile.json") as f:
        profile = json.load(f)

    jobs = get_all_jobs(limit=100000)
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    details = matcher_explain(profile, job)

    prose = None
    if GEMINI_ENABLED:
        prose = explain_score_prose(
            details["total_score"],
            job.get("title", ""),
            job.get("company", ""),
            details["matched_skills"],
            details["missing_skills"],
        )
    details["ai_explanation"] = prose or ""
    details["job"] = {
        "id": job.get("id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "url": job.get("url"),
        "source": job.get("source"),
    }
    return jsonify(details)


# ── Manual profile editing ───────────────────────────────────────────────────
@app.route("/api/profile/update", methods=["POST"])
def update_profile():
    """
    Update fields of profile.json (add/remove skills, edit name, college, etc.).
    Body: {field: value, field2: value2}. Only whitelisted fields can be changed.
    Triggers a background rescore on skill changes.
    """
    if not os.path.exists("profile.json"):
        return jsonify({"error": "No profile to edit. Upload a resume first."}), 400

    data = request.get_json() or {}
    ALLOWED_FIELDS = {"name", "email", "phone", "college", "current_course",
                      "year_of_study", "skills", "projects", "experience",
                      "certifications", "education"}
    updates = {k: v for k, v in data.items() if k in ALLOWED_FIELDS}
    if not updates:
        return jsonify({"error": "No valid fields to update."}), 400

    with open("profile.json") as f:
        profile = json.load(f)

    profile.update(updates)

    # Keep summary.all_skills in sync if skills changed
    if "skills" in updates:
        skills_list = flatten_skills(updates["skills"])
        profile["skills"] = skills_list
        profile.setdefault("summary", {})["all_skills"] = skills_list

    with open("profile.json", "w") as f:
        json.dump(profile, f, indent=2)

    # Kick off background rescore if skills changed
    if "skills" in updates and not rescore_status.get("running"):
        threading.Thread(target=_rescore_all_jobs, args=(profile,), daemon=True).start()

    return jsonify({"success": True, "profile": profile, "rescoring": "skills" in updates})


@app.route("/api/profile/add-skill", methods=["POST"])
def add_skill():
    """Adds a single skill to the profile."""
    data = request.get_json() or {}
    new_skill = (data.get("skill") or "").strip().lower()
    if not new_skill:
        return jsonify({"error": "skill required"}), 400

    if not os.path.exists("profile.json"):
        return jsonify({"error": "No profile"}), 400

    with open("profile.json") as f:
        profile = json.load(f)

    skills = flatten_skills(profile.get("skills", []))
    if new_skill in [s.lower() for s in skills]:
        return jsonify({"error": "Skill already exists", "skills": skills}), 400

    skills.append(new_skill)
    profile["skills"] = skills
    profile.setdefault("summary", {})["all_skills"] = skills

    with open("profile.json", "w") as f:
        json.dump(profile, f, indent=2)

    if not rescore_status.get("running"):
        threading.Thread(target=_rescore_all_jobs, args=(profile,), daemon=True).start()

    return jsonify({"success": True, "skills": skills, "rescoring": True})


@app.route("/api/profile/remove-skill", methods=["POST"])
def remove_skill():
    """Removes a single skill from the profile."""
    data = request.get_json() or {}
    skill_to_remove = (data.get("skill") or "").strip().lower()
    if not skill_to_remove:
        return jsonify({"error": "skill required"}), 400

    if not os.path.exists("profile.json"):
        return jsonify({"error": "No profile"}), 400

    with open("profile.json") as f:
        profile = json.load(f)

    skills = flatten_skills(profile.get("skills", []))
    filtered = [s for s in skills if s.lower() != skill_to_remove]
    if len(filtered) == len(skills):
        return jsonify({"error": "Skill not found", "skills": skills}), 404

    profile["skills"] = filtered
    profile.setdefault("summary", {})["all_skills"] = filtered

    with open("profile.json", "w") as f:
        json.dump(profile, f, indent=2)

    if not rescore_status.get("running"):
        threading.Thread(target=_rescore_all_jobs, args=(profile,), daemon=True).start()

    return jsonify({"success": True, "skills": filtered, "rescoring": True})


# ── User interaction tracking (for preference learning) ──────────────────────
def _init_interactions_table():
    """Tracks user interactions with jobs for future preference learning."""
    import sqlite3
    conn = sqlite3.connect("searchy.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_interactions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id        INTEGER NOT NULL,
            action        TEXT NOT NULL,
            ts            REAL NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_interactions_action ON user_interactions(action)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_interactions_ts ON user_interactions(ts)")
    conn.commit()
    conn.close()


# Init on import (safe — idempotent)
try:
    _init_interactions_table()
except Exception as e:
    print(f"[init] Could not create interactions table: {e}")


@app.route("/api/track-interaction", methods=["POST"])
def track_interaction():
    """
    Record a user action on a job. Used later to learn preferences.
    Body: {job_id: int, action: 'view'|'click'|'save'|'unsave'|'apply'|'dismiss'}
    """
    import sqlite3, time
    data = request.get_json() or {}
    job_id = data.get("job_id")
    action = (data.get("action") or "").strip().lower()
    if not job_id or action not in {"view", "click", "save", "unsave", "apply", "dismiss"}:
        return jsonify({"error": "job_id and valid action required"}), 400

    try:
        conn = sqlite3.connect("searchy.db")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_interactions (job_id, action, ts) VALUES (?, ?, ?)",
            (int(job_id), action, time.time()),
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/interaction-stats", methods=["GET"])
def interaction_stats():
    """Returns counts of each interaction type, useful for Analytics tab."""
    import sqlite3
    try:
        conn = sqlite3.connect("searchy.db")
        cur = conn.cursor()
        cur.execute("SELECT action, COUNT(*) FROM user_interactions GROUP BY action")
        rows = cur.fetchall()
        conn.close()
        return jsonify({row[0]: row[1] for row in rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("🚀 JobSearchy running at http://localhost:5000")
    print("📄 Accepts: PDF, DOCX, DOC")
    app.run(debug=True, host="0.0.0.0", port=5000)