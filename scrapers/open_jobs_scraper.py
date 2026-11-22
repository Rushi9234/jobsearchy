"""
scrapers/open_jobs_scraper.py — Open Global & Indian Tech Jobs Scraper
Sources:
  1. Jobicy API (https://jobicy.com/api/v2/remote-jobs) — Free open REST API for tech jobs & internships
  2. Arbeitnow API (https://www.arbeitnow.com/api/job-board-api) — Free open REST API for software & data roles
"""

import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger("jobsearchy.scrapers.open_jobs")

TIMEOUT = 4
HEADERS = {
    "User-Agent": "JobSearchyBot/2.0 (Student Job Aggregator; github.com/Rushi9234/jobsearchy)",
    "Accept": "application/json",
}


def _build_id(source: str, identifier: str) -> str:
    return f"{source}_{hashlib.md5(identifier.encode('utf-8')).hexdigest()[:10]}"


def scrape_jobicy(keywords: Optional[List[str]] = None, limit: int = 15) -> List[Dict[str, Any]]:
    """Fetches tech roles from Jobicy API with zero rate-limit blocks."""
    results = []
    now_str = datetime.now().isoformat() + "Z"
    tag = "python"
    if keywords:
        # Choose a relevant tag from keywords
        for kw in keywords:
            if kw.lower() in ("python", "react", "javascript", "backend", "data", "devops"):
                tag = kw.lower()
                break

    url = f"https://jobicy.com/api/v2/remote-jobs?count={limit}&tag={tag}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("jobs", [])
            for item in items:
                title = item.get("jobTitle", "").strip()
                company = item.get("companyName", "").strip()
                link = item.get("url", "").strip()
                if not title or not link:
                    continue

                desc = item.get("jobDescription", "")
                # Clean html tags
                import re
                clean_desc = re.sub(r"<[^>]+>", " ", desc).strip()[:400]

                tags = [t.lower().strip() for t in item.get("jobTags", [])]
                tags += ["remote", "tech", tag]

                results.append({
                    "job_id":      _build_id("jobicy", link),
                    "source":      "jobicy_remote",
                    "title":       title,
                    "company":     company,
                    "location":    item.get("jobGeo", "Remote"),
                    "duration":    item.get("jobType", "Full-Time"),
                    "stipend":     item.get("salary", "Competitive"),
                    "url":         link,
                    "tags":        list(set(tags)),
                    "description": f"{title} at {company}. {clean_desc}",
                    "job_type":    "job",
                    "scraped_at":  now_str,
                })
    except Exception as e:
        logger.warning(f"[OpenJobs] Jobicy scrape failed: {e}")

    return results


def scrape_arbeitnow(keywords: Optional[List[str]] = None, limit: int = 15) -> List[Dict[str, Any]]:
    """Fetches developer & data jobs from Arbeitnow open API."""
    results = []
    now_str = datetime.now().isoformat() + "Z"
    url = "https://www.arbeitnow.com/api/job-board-api"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", [])
            keyword_set = {k.lower().strip() for k in (keywords or ["python", "data", "engineer", "react"])}

            for item in items[:limit * 2]:
                title = item.get("title", "").strip()
                company = item.get("company_name", "").strip()
                link = item.get("url", "").strip()
                tags = [t.lower().strip() for t in item.get("tags", [])]

                full_text = f"{title} {company} {' '.join(tags)}".lower()
                if not any(k in full_text for k in keyword_set):
                    continue

                import re
                clean_desc = re.sub(r"<[^>]+>", " ", item.get("description", "")).strip()[:400]

                results.append({
                    "job_id":      _build_id("arbeitnow", link),
                    "source":      "arbeitnow",
                    "title":       title,
                    "company":     company,
                    "location":    item.get("location", "Remote"),
                    "duration":    "Full-Time" if not item.get("remote") else "Remote",
                    "stipend":     "Competitive",
                    "url":         link,
                    "tags":        tags,
                    "description": f"{title} at {company}. {clean_desc}",
                    "job_type":    "job",
                    "scraped_at":  now_str,
                })
                if len(results) >= limit:
                    break
    except Exception as e:
        logger.warning(f"[OpenJobs] Arbeitnow scrape failed: {e}")

    return results


def scrape_open_jobs(keywords: Optional[List[str]] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Aggregates all open developer APIs."""
    all_jobs = []
    all_jobs.extend(scrape_jobicy(keywords, limit=limit // 2))
    all_jobs.extend(scrape_arbeitnow(keywords, limit=limit // 2))
    logger.info(f"[OpenJobs] Total scraped from open APIs: {len(all_jobs)}")
    return all_jobs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    jobs = scrape_open_jobs(["python", "data"])
    print(f"Total jobs: {len(jobs)}")
    for j in jobs[:3]:
        print(f" - [{j['source']}] {j['title']} @ {j['company']}")
