"""
main.py — Searchy Orchestrator
One function to run the entire pipeline:
  Resume → Scrape → Filter → Score → DB → Notify
Call this directly or let scheduler.py call it on a schedule.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# ── Add project root to path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT / "searchy.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("searchy.main")

from database.db import init_db, insert_job, mark_seen, is_seen, get_unnotified_jobs, \
    mark_notified, log_scrape, get_stats
from utils.resume_parser import load_profile, parse_resume, save_profile
from utils.matcher import batch_score
from utils.filters import filter_jobs
from scrapers.internshala_scraper import scrape as scrape_internshala
from scrapers.company_scraper import scrape_linkedin

def _safe_import(fn_name, module):
    try:
        import importlib
        mod = importlib.import_module(module)
        return getattr(mod, fn_name)
    except Exception as e:
        logger.warning("Optional scraper %s.%s not available: %s", module, fn_name, e)
        return lambda **kwargs: []

scrape_unstop      = _safe_import('scrape_unstop',      'scrapers.unstop_scraper')
scrape_devfolio    = _safe_import('scrape_devfolio',    'scrapers.devfolio_scraper')
scrape_hackerearth = _safe_import('scrape_hackerearth', 'scrapers.hackerearth_scraper')
scrape_wellfound   = _safe_import('scrape_wellfound',   'scrapers.wellfound_scraper')
scrape_naukri      = _safe_import('scrape_naukri',      'scrapers.naukri_scraper')
scrape_govt        = _safe_import('scrape_govt_jobs',   'scrapers.govt_scraper')
scrape_pmis        = _safe_import('scrape_pmis_jobs',   'scrapers.pmis_scraper')
scrape_open_jobs   = _safe_import('scrape_open_jobs',   'scrapers.open_jobs_scraper')
from notifiers.telegram_notifier import send_job_alerts, send_daily_digest as tg_digest
from notifiers.email_notifier import send_daily_digest as email_digest


# ── Config ─────────────────────────────────────────────────────────────────────
SCRAPE_KEYWORDS = [
    # Core data/ML
    "python", "machine learning", "data science", "data analyst",
    "data analytics", "nlp", "deep learning",
    # Research/Quant (Rushikesh's profile)
    "econometrics", "quantitative research", "statistical analysis",
    "business analytics", "research analyst", "data research",
    "xgboost", "predictive modeling", "statistical modeling",
    # Web/Backend (for broader coverage)
    "flask", "django", "react", "backend", "api",
]
MIN_SCORE_FOR_ALERT    = 30.0   # Send real-time alert above this score
MIN_SCORE_FOR_DIGEST   = 20.0   # Include in daily digest above this
PAGES_PER_KEYWORD      = 1      # Internshala pages per keyword
FETCH_FULL_DESCRIPTION = False  # True = slower but better scoring


def run_pipeline(
    send_telegram: bool = True,
    send_email:    bool = True,
    digest_only:   bool = False,
) -> dict:
    """
    Full Searchy pipeline. Returns a summary dict with counts.
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("  SEARCHY PIPELINE STARTED — %s", start_time.strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 60)

    # ── Step 1: Ensure DB is ready ────────────────────────────────────────────
    init_db()

    # ── Step 2: Load user profile ─────────────────────────────────────────────
    try:
        profile = load_profile()
        logger.info("Profile loaded: %s | Skills: %d",
                    profile.get("name"), len(profile.get("summary", {}).get("all_skills", [])))
    except FileNotFoundError:
        logger.error("No profile.json found. Run: python utils/resume_parser.py <resume.pdf>")
        return {"error": "no_profile"}

    # ── Step 3: Scrape all sources in parallel ────────────────────────────────
    from concurrent.futures import ThreadPoolExecutor, as_completed

    scraper_configs = [
        ("Internshala", scrape_internshala, SCRAPE_KEYWORDS, "internship"),
        ("LinkedIn",    scrape_linkedin,    SCRAPE_KEYWORDS, "job"),
        ("Wellfound",   scrape_wellfound,   SCRAPE_KEYWORDS, "job"),
        ("Unstop",      scrape_unstop,      SCRAPE_KEYWORDS, "hackathon"),
        ("Devfolio",    scrape_devfolio,    SCRAPE_KEYWORDS, "hackathon"),
        ("HackerEarth", scrape_hackerearth, SCRAPE_KEYWORDS, "hackathon"),
        ("Naukri",      scrape_naukri,      SCRAPE_KEYWORDS, "job"),
        ("Govt",        lambda **kw: scrape_govt(), None, "internship"),
        ("PMIS",        lambda **kw: scrape_pmis(keywords=kw.get("keywords")), SCRAPE_KEYWORDS, "internship"),
        ("OpenJobs",    lambda **kw: scrape_open_jobs(keywords=kw.get("keywords")), SCRAPE_KEYWORDS, "job"),
    ]

    def _run(name, fn, kw, jtype):
        try:
            try:
                jobs = fn(keywords=kw)
            except TypeError:
                jobs = fn(keywords=kw[:3])
            for j in jobs:
                j.setdefault("job_type", jtype)
            logger.info("  %s → %d listings", name, len(jobs))
            log_scrape(name.lower(), "success", len(jobs))
            return jobs
        except Exception as e:
            logger.error("  %s failed: %s", name, e)
            log_scrape(name.lower(), "error", message=str(e))
            return []

    all_raw_jobs = []
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {executor.submit(_run, n, fn, kw, jt): n for n, fn, kw, jt in scraper_configs}
        for future in as_completed(futures):
            all_raw_jobs.extend(future.result())

    logger.info("Total raw listings: %d", len(all_raw_jobs))

    # ── Step 4: Deduplicate against seen_jobs ─────────────────────────────────
    new_jobs = [
        j for j in all_raw_jobs
        if not is_seen(j["job_id"], j["source"])
    ]
    logger.info("New (unseen) listings: %d", len(new_jobs))

    if not new_jobs:
        logger.info("No new listings. Pipeline done.")
        return {"scraped": len(all_raw_jobs), "new": 0, "notified": 0}

    # ── Step 5: Filter ────────────────────────────────────────────────────────
    accepted, rejected = filter_jobs(new_jobs)
    logger.info("After filters: %d accepted, %d rejected", len(accepted), len(rejected))

    # ── Step 6: Score ─────────────────────────────────────────────────────────
    scored_jobs = batch_score(profile, accepted)
    logger.info("Scoring complete. Top score: %.1f",
                scored_jobs[0]["match_score"] if scored_jobs else 0)

    # ── Step 7: Persist to DB + mark seen ────────────────────────────────────
    saved_count = 0
    for job in scored_jobs:
        if insert_job(job):
            saved_count += 1
        mark_seen(job["job_id"], job["source"])

    # Also mark rejected jobs as seen so we don't re-evaluate them
    for job in rejected:
        mark_seen(job["job_id"], job["source"])

    logger.info("Saved %d new jobs to DB", saved_count)

    # ── Step 8: Notify ────────────────────────────────────────────────────────
    high_score_jobs = [j for j in scored_jobs if j["match_score"] >= MIN_SCORE_FOR_ALERT]
    digest_jobs     = [j for j in scored_jobs if j["match_score"] >= MIN_SCORE_FOR_DIGEST]
    notified_ids    = []

    if send_telegram and not digest_only and high_score_jobs:
        logger.info("Sending %d Telegram alerts...", len(high_score_jobs))
        sent = send_job_alerts(high_score_jobs)
        logger.info("  Telegram: %d sent", sent)

    if send_email and digest_jobs:
        logger.info("Sending email digest (%d jobs)...", len(digest_jobs))
        ok = email_digest(digest_jobs)
        logger.info("  Email: %s", "sent" if ok else "failed")

    if digest_only and send_telegram and digest_jobs:
        tg_digest(digest_jobs[:10])

    # Mark all alerted jobs as notified
    notified_ids = [j.get("id") or j.get("job_id") for j in high_score_jobs if (j.get("id") or j.get("job_id"))]
    if notified_ids:
        mark_notified(notified_ids)

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = (datetime.now() - start_time).seconds
    stats   = get_stats()
    summary = {
        "scraped":      len(all_raw_jobs),
        "new":          len(new_jobs),
        "filtered_out": len(rejected),
        "accepted":     len(accepted),
        "saved":        saved_count,
        "alerted":      len(high_score_jobs),
        "elapsed_sec":  elapsed,
        "db_stats":     stats,
    }
    logger.info("Pipeline complete in %ds | %s", elapsed, summary)
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Searchy — AI Job Hunter")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram alerts")
    parser.add_argument("--no-email",    action="store_true", help="Disable email digest")
    parser.add_argument("--digest-only", action="store_true", help="Send digest mode only")
    parser.add_argument("--parse-resume", metavar="PDF",      help="Parse a new resume PDF first")
    args = parser.parse_args()

    if args.parse_resume:
        profile = parse_resume(args.parse_resume)
        save_profile(profile)
        print(f"✓ Profile updated for: {profile['name']}")

    result = run_pipeline(
        send_telegram=not args.no_telegram,
        send_email=not args.no_email,
        digest_only=args.digest_only,
    )
    print("\n" + "=" * 40)
    print("  Searchy Run Complete")
    print("=" * 40)
    for k, v in result.items():
        if k != "db_stats":
            print(f"  {k:<16}: {v}")
    print("=" * 40)
