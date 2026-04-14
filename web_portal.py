import os
import sys
import json
import threading
import sqlite3
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.resume_parser import parse_resume
from utils.matcher import batch_score
from utils.filters import filter_jobs
from database.db import (
    init_db, get_all_jobs, get_top_jobs, get_saved_jobs,
    toggle_saved, get_stats, insert_job, is_seen, mark_seen,
    get_tracker_entries, add_tracker_entry, update_tracker_stage, delete_tracker_entry
)
from scrapers.internshala_scraper import scrape as scrape_internshala
from scrapers.company_scraper import scrape_linkedin

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
    """Rescore every job in DB against a new profile. Called after resume upload."""
    try:
        conn = sqlite3.connect("searchy.db")
        cur  = conn.cursor()
        cur.execute("SELECT id, title, company, description, tags FROM jobs")
        rows = cur.fetchall()
        if not rows:
            conn.close()
            return 0
        job_list = []
        for row in rows:
            jid, title, company, desc, tags = row
            try:
                tag_list = json.loads(tags) if tags else []
            except:
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
                (job.get("match_score", 0), job["id"])
            )
        conn.commit()
        conn.close()
        print(f"[Upload] Rescored {len(scored)} jobs for {profile.get('name')}")
        return len(scored)
    except Exception as e:
        print(f"[Upload] Rescore error: {e}")
        return 0


# ── Serve frontend ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Upload resume ─────────────────────────────────────────────────────────────
@app.route("/api/upload-resume", methods=["POST"])
def upload_resume():
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

        # ── Auto-rescore all existing DB jobs against this new profile ──
        rescored = _rescore_all_jobs(profile)

        return jsonify({
            "success":  True,
            "profile":  profile,
            "rescored": rescored,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Get profile ───────────────────────────────────────────────────────────────
@app.route("/api/profile", methods=["GET"])
def get_profile():
    if not os.path.exists("profile.json"):
        return jsonify({"error": "No profile found"}), 404
    with open("profile.json") as f:
        return jsonify(json.load(f))


# ── Run pipeline ──────────────────────────────────────────────────────────────
def run_pipeline_thread(days=7):
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

        all_skills = flatten_skills(profile.get("skills", []))
        keywords = all_skills[:6] if all_skills else ["python", "data science", "machine learning"]

        pipeline_status["message"]  = "Launching all scrapers in parallel..."
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

        pipeline_status["message"]  = f"AI scoring {len(accepted)} jobs..."
        pipeline_status["progress"] = 75
        result = batch_score(dict(profile), accepted)
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
        if "job_type" not in j:
            src   = (j.get("source",  "") or "").lower()
            title = (j.get("title",   "") or "").lower()
            if any(s in src for s in ["unstop", "devfolio", "hackerearth"]) or \
               any(k in title for k in ["hackathon", "challenge", "competition", "datathon"]):
                j["job_type"] = "hackathon"
            elif any(s in src for s in ["govt_internshala", "govt_portal", "linkedin_govt",
                                         "niti_aayog", "mygov"]) or \
                 any(k in title for k in ["government", "niti aayog", "isro", "drdo", "aicte"]):
                j["job_type"] = "govt"
            elif "internship" in title or "intern" in title or "internshala" in src:
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

    return jsonify(jobs)


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

        result = send_daily_digest(
            jobs,
            recipient_email=recipient_email if recipient_email else None,
            user_name=user_name,
            all_skills=all_skills,
        )
        if result:
            return jsonify({"success": True, "message": "Email sent!"})
        else:
            return jsonify({"error": "Email failed. Check searchy.env credentials."}), 500
    except Exception as e:
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


if __name__ == "__main__":
    print("🚀 JobSearchy running at http://localhost:5000")
    print("📄 Accepts: PDF, DOCX, DOC")
    app.run(debug=True, host="0.0.0.0", port=5000)
