import os
import sys
import json
import logging
import threading
import time
import sqlite3
import re
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "searchy.env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    else:
        load_dotenv()
except Exception:
    pass

from utils.resume_parser import parse_resume
try:
    from utils.resume_llm_parser import parse_resume_hybrid
except ImportError:
    parse_resume_hybrid = parse_resume
from utils.matcher import batch_score, batch_score_and_coverage, coverage_score, explain_score as matcher_explain
from utils.filters import filter_jobs
from utils.career_gps import evaluate_career_gps
from utils.joby_copilot import generate_joby_reply
from database.db import (
    get_conn, init_db, get_all_jobs, get_jobs_filtered, get_top_jobs, get_saved_jobs,
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
scrape_pmis        = _safe_import('scrape_pmis_jobs',   'scrapers.pmis_scraper')
scrape_open_jobs   = _safe_import('scrape_open_jobs',   'scrapers.open_jobs_scraper')
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
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM jobs")
            total = cur.fetchone()[0] or 0

            rescore_status = {"running": True, "done": 0, "total": total, "message": "Starting rescore..."}

            if total == 0:
                rescore_status = {"running": False, "done": 0, "total": 0, "message": "No jobs to rescore"}
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


@app.route("/<path:filename>")
def serve_static(filename):
    if not filename.startswith("api/") and os.path.exists(os.path.join("static", filename)):
        return send_from_directory("static", filename)
    return send_from_directory("static", "index.html")


@app.route("/api/download-handbook", methods=["GET"])
def download_handbook():
    """Serves the master Senior Engineering Handbook PDF."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "JobSearchy_Senior_Engineering_Handbook.pdf")
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name="JobSearchy_Senior_Engineering_Handbook.pdf")
    return jsonify({"error": "Handbook PDF not generated yet"}), 404


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
        profile = parse_resume_hybrid(filepath)

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


def _get_active_profile() -> dict:
    if os.path.exists("profile.json"):
        try:
            with open("profile.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read profile.json: {e}")
            return {}
    return {}


# ── Get profile ───────────────────────────────────────────────────────────────
@app.route("/api/profile", methods=["GET"])
def get_profile():
    profile = _get_active_profile()
    if not profile:
        return jsonify({"error": "No profile found"}), 404
    return jsonify(profile)


# ── Dynamic Career GPS ────────────────────────────────────────────────────────
@app.route("/api/career-gps", methods=["GET"])
def get_career_gps():
    """
    Returns dynamic, personalized career trajectory data, role paths,
    skill gaps from active jobs in DB, and a 7-day action plan.
    """
    profile = _get_active_profile()
    try:
        jobs = get_all_jobs(limit=300)
    except Exception as e:
        logger.warning(f"[CareerGPS] Failed to load jobs from DB: {e}")
        jobs = []

    data = evaluate_career_gps(profile=profile, jobs=jobs)
    return jsonify(data)


# ── Joby AI Career Copilot ───────────────────────────────────────────────────
@app.route("/api/joby-chat", methods=["POST"])
def joby_chat():
    """
    Joby AI Career Copilot endpoint.
    Accepts: { message: str, history?: list }
    Returns: { reply: str, model: str, status: 'success' }
    """
    body = request.get_json(silent=True) or {}
    message = body.get("message", "").strip()
    history = body.get("history", [])

    if not message:
        return jsonify({"error": "Empty message", "status": "error"}), 400

    profile = _get_active_profile()
    try:
        top_jobs = get_top_jobs(limit=5, min_score=40.0)
    except Exception:
        top_jobs = []

    try:
        jobs = get_all_jobs(limit=100)
    except Exception:
        jobs = []

    career_gps = evaluate_career_gps(profile=profile, jobs=jobs)
    response = generate_joby_reply(
        message=message,
        history=history,
        profile=profile,
        top_jobs=top_jobs,
        career_gps=career_gps
    )
    return jsonify(response)



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
        _time.sleep(600)  # 10 min — Render free tier is slow, govt scraper is slow
        if pipeline_status.get("running"):
            pipeline_status["running"]  = False
            pipeline_status["message"]  = "Pipeline timed out after 10 min — partial results saved."
            pipeline_status["progress"] = 100
            print("[Pipeline] Watchdog triggered — forced completion after 10 min")
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
            ("PMIS",        lambda **kw: scrape_pmis(keywords=kw.get("keywords")), keywords, "internship"),
            ("OpenJobs",    lambda **kw: scrape_open_jobs(keywords=kw.get("keywords")), keywords, "job"),
        ]

        all_jobs = []
        scraper_results = {}
        progress_step = 40 / len(scraper_configs)

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_name = {
                executor.submit(_run_scraper, name, fn, kw, jtype, days): name
                for name, fn, kw, jtype in scraper_configs
            }
            completed = 0
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    jobs = future.result(timeout=60)
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


def _run_scraper(source_name, scraper_fn, keywords, default_job_type, days=7):
    try:
        try:
            jobs = scraper_fn(keywords=keywords, days=days)
        except TypeError:
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


def is_listing_expired(j: dict) -> bool:
    """Returns True if the hackathon or internship is closed / past deadline."""
    title = (j.get("title") or "").lower()
    desc = (j.get("description") or "").lower()
    combined = f"{title} {desc}"

    closed_signals = [
        "registration closed", "registrations closed", "applications closed",
        "no longer accepting applications", "application deadline passed",
        "competition ended", "hackathon ended", "event concluded", "submission closed"
    ]
    if any(sig in combined for sig in closed_signals):
        return True

    patterns = [
        r"(?:last date|deadline|closing date|apply by|register by|ends?)[:\s]+(\d{1,2}[\s\-\/](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-\/,]*\d{2,4})",
        r"(?:last date|deadline)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    ]
    for pat in patterns:
        m = re.search(pat, j.get("description") or "", re.IGNORECASE)
        if m:
            date_str = m.group(1).strip()
            for fmt in ("%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    dt = datetime.strptime(date_str, fmt)
                    if dt.year < 2000:
                        dt = dt.replace(year=dt.year + 2000)
                    if dt < datetime.now():
                        return True
                except Exception:
                    pass
    return False


def _calc_days_ago(scraped_at_str: str) -> int:
    if not scraped_at_str:
        return 0
    try:
        s = str(scraped_at_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.now()
        diff = now - dt
        return max(0, diff.days)
    except Exception:
        return 0


def classify_job(j: dict) -> str:
    """
    Deterministically classifies a listing into 'hackathon', 'govt', 'internship', or 'job'.
    Eliminates false positives where private companies were tagged as govt, and full-time roles as internship.
    """
    src = (j.get("source") or "").lower()
    title = (j.get("title") or "").lower()
    company = (j.get("company") or "").lower()
    url = (j.get("url") or "").lower()
    stipend = (j.get("stipend") or "").lower()
    duration = (j.get("duration") or "").lower()
    tags = " ".join(j.get("tags", []) if isinstance(j.get("tags"), list) else []).lower()
    combined = f"{title} {company} {src} {tags}"

    # 1. HACKATHONS & COMPETITIONS
    if any(s in src for s in ["unstop", "devfolio", "hackerearth"]) or \
       any(k in combined for k in ["hackathon", "challenge", "competition", "datathon", "ideathon", "sprint", "buildathon", "ctf"]):
        return "hackathon"

    # 2. REAL GOVERNMENT / PMIS
    govt_entities = [
        "pm internship scheme", "pminternship", "pmis", "ministry of",
        "niti aayog", "isro", "drdo", "aicte", "csir", "nabard", "nic.in",
        "meity", "rbi", "sebi", "bhel", "ongc", "iocl", "ntpc", "sail", "hal",
        "national career service", "upsc", "ssc", "government of india", "govt of",
        "iit kanpur", "iit roorkee", "iit bombay", "iit delhi", "iit madras", "iit kharagpur",
        "dst-inspire", "icar", "nielit", "dst", "c-dac"
    ]
    is_govt_source = any(s in src for s in ["pmis", "niti_aayog", "mygov", "aicte", "govt_portal", "linkedin_govt"]) or \
                     any(d in url for d in [
                         "pminternship.mca.gov.in", "aicte-india.org", "niti.gov.in", "gov.in",
                         "nic.in", "isro.gov.in", "drdo.gov.in", "csir.res.in", "surge.iitk.ac.in",
                         "spark.iitr.ac.in", "sebi.gov.in", "rbi.org.in", "nabard.org", "nielit.gov.in", "icar.org.in"
                     ])
    is_govt_company = any(k in company for k in govt_entities)
    is_govt_title = any(k in title for k in govt_entities)
    private_signals = [
        "pvt ltd", "pvt. ltd", "private limited", "ltd.", "llp", "inc.",
        "technologies", "consultancy", "solutions", "wedding", "elevate labs",
        "corporation private", "services pvt"
    ]
    is_private_co = any(p in company for p in private_signals)
    is_official_override = any(g in company or g in title for g in [
        "government of india", "ministry of", "isro", "drdo", "aicte",
        "niti aayog", "pm internship", "pminternship", "iit kanpur", "iit roorkee"
    ])

    if (is_govt_source or is_govt_company or is_govt_title) and (not is_private_co or is_official_override):
        return "govt"

    # 3. INTERNSHIP vs FULL-TIME JOB
    intern_keywords = ["intern", "internship", "trainee", "apprentice", "fellow", "fellowship"]
    full_time_keywords = ["full time", "full-time", "lead", "senior", "principal", "staff engineer", "head of", "director"]

    has_intern_title = any(k in title for k in intern_keywords)
    has_full_time = any(k in title for k in full_time_keywords) or any(k in duration for k in ["full time", "full-time", "permanent"])
    has_monthly_stipend = "/month" in stipend or "/mo" in stipend or "stipend" in stipend or "unpaid" in stipend
    has_annual_lpa = "lpa" in stipend or "per annum" in stipend or "yr" in stipend

    if has_full_time and not has_intern_title:
        return "job"
    if has_intern_title:
        return "internship"
    if has_monthly_stipend and not has_annual_lpa:
        return "internship"
    if has_annual_lpa:
        return "job"
    if "month" in duration:
        return "internship"

    return "job"


# ── Jobs API ──────────────────────────────────────────────────────────────────
@app.route("/api/jobs", methods=["GET"])
def get_jobs():
    limit        = request.args.get("limit",        100, type=int)
    min_score    = request.args.get("min_score",    0,   type=int)
    source       = request.args.get("source",       "")
    search       = request.args.get("search",       "")
    hide_expired = request.args.get("hide_expired", "1") == "1"
    days         = request.args.get("days",         None, type=int)
    job_type     = request.args.get("job_type",     "")

    # High-performance SQL-indexed date & score pre-filtering (bypasses heavy Python memory loops)
    fetch_limit = 1000 if (job_type or search) else max(limit or 100, 100)
    jobs = get_jobs_filtered(
        days=days,
        min_score=float(min_score or 0.0),
        source=source if source else None,
        limit=fetch_limit,
    )

    classified_jobs = []
    for j in jobs:
        if "match_score" in j and "score" not in j:
            j["score"] = j["match_score"]
        j["job_type"] = classify_job(j)
        j["is_expired"] = is_listing_expired(j)
        if hide_expired and j["is_expired"]:
            continue

        # Calculate freshness
        src = (j.get("source") or "").lower()
        if "portal" in src or "static" in src or "pmis" in src:
            j["days_ago"] = 0
        else:
            j["days_ago"] = _calc_days_ago(j.get("scraped_at", ""))

        if days is not None and j["days_ago"] > days:
            continue

        classified_jobs.append(j)

    jobs = classified_jobs

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
    try:
        if os.path.exists("profile.json"):
            with open("profile.json") as f:
                profile = json.load(f)
            profile_skills = (
                profile.get("summary", {}).get("all_skills")
                or flatten_skills(profile.get("skills", []))
            )
            if profile_skills:
                for j in jobs[:200]:
                    cov = coverage_score(profile_skills, j)
                    j["coverage_pct"]   = cov["coverage_pct"]
                    j["coverage_level"] = cov["level"]
                    j["coverage_matched"] = cov["matched"]
                    j["coverage_missing"] = cov["missing"]
    except Exception as e:
        logger.warning("[api/jobs] coverage computation failed: %s", e)

    # Coverage filter
    min_cov = request.args.get("min_coverage", 0, type=int)
    if min_cov > 0:
        jobs = [j for j in jobs if j.get("coverage_pct", 0) >= min_cov]

    if limit and len(jobs) > limit:
        jobs = jobs[:limit]

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
        days            = data.get("days", None)
        jobs            = get_top_jobs(limit=100)

        if days is not None:
            cutoff = datetime.now() - timedelta(days=int(days))
            fresh_jobs = []
            for j in jobs:
                src = (j.get("source") or "").lower()
                if "portal" in src or "static" in src or "pmis" in src:
                    fresh_jobs.append(j)
                    continue
                try:
                    s = str(j.get("scraped_at", "")).replace("Z", "")
                    dt = datetime.fromisoformat(s)
                    if dt >= cutoff:
                        fresh_jobs.append(j)
                except Exception:
                    fresh_jobs.append(j)
            jobs = fresh_jobs[:50]
        else:
            jobs = jobs[:50]

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
            return jsonify({
                "error": "Email delivery failed. Render free tier blocks outbound SMTP ports (465/587). Please set RESEND_API_KEY in environment variables for instant HTTPS delivery, or verify MAIL_FROM and MAIL_PASS."
            }), 500
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
    try:
        with get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_interactions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id        INTEGER NOT NULL,
                    action        TEXT NOT NULL,
                    ts            REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_action ON user_interactions(action)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_ts ON user_interactions(ts)")
    except Exception as e:
        logger.warning(f"[init] Could not create interactions table: {e}")


# Init on import (safe — idempotent)
try:
    _init_interactions_table()
except Exception as e:
    logger.warning(f"[init] Could not create interactions table: {e}")


@app.route("/api/track-interaction", methods=["POST"])
def track_interaction():
    """
    Record a user action on a job. Used later to learn preferences.
    Body: {job_id: int, action: 'view'|'click'|'save'|'unsave'|'apply'|'dismiss'}
    """
    data = request.get_json() or {}
    job_id = data.get("job_id")
    action = (data.get("action") or "").strip().lower()
    if not job_id or action not in {"view", "click", "save", "unsave", "apply", "dismiss"}:
        return jsonify({"error": "job_id and valid action required"}), 400

    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO user_interactions (job_id, action, ts) VALUES (?, ?, ?)",
                (int(job_id), action, time.time()),
            )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/interaction-stats", methods=["GET"])
def interaction_stats():
    """Returns counts of each interaction type, useful for Analytics tab."""
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT action, COUNT(*) FROM user_interactions GROUP BY action").fetchall()
            return jsonify({row[0]: row[1] for row in rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── In-App Scheduled Automation (4x Daily Pipeline for Production) ────────────
_scheduler_started = False

def _start_background_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def _loop():
        time.sleep(60)
        while True:
            try:
                logger.info("[AutoScheduler] Triggering periodic scrape pipeline...")
                from main import run_pipeline
                run_pipeline(send_telegram=True, send_email=True, digest_only=True)
            except Exception as e:
                logger.warning(f"[AutoScheduler] Periodic pipeline run skipped: {e}")
            time.sleep(21600)

    t = threading.Thread(target=_loop, daemon=True, name="JobSearchyAutoScheduler")
    t.start()
    logger.info("[AutoScheduler] In-app 4x daily automation thread initialized.")

if os.getenv("ENABLE_SCHEDULER", "0") == "1" or __name__ == "__main__":
    _start_background_scheduler()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("[JobSearchy] Server starting at http://localhost:5000")
    print("[JobSearchy] Supported Resume Formats: PDF, DOCX, DOC")
    app.run(debug=True, host="0.0.0.0", port=5000)
