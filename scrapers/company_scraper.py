"""
company_scraper.py — Searchy Multi-Source Job Scraper
Scrapes LinkedIn (public), Unstop, and Wellfound for internships/fresher roles.
Uses requests + BeautifulSoup. No API keys required.
"""

import re
import time
import hashlib
import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY   = 2.0
TIMEOUT = 15


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _safe_get(session, url: str, params: Optional[dict] = None) -> Optional[requests.Response]:
    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r
            logger.warning("HTTP %d → %s (attempt %d)", r.status_code, url, attempt + 1)
            if r.status_code in (429, 503):
                time.sleep(5 * (attempt + 1))
        except requests.RequestException as e:
            logger.warning("Request error: %s", e)
            time.sleep(DELAY)
    return None


def _job_id(source: str, url: str) -> str:
    return f"{source}_{hashlib.md5(url.encode()).hexdigest()[:10]}"


# ── LinkedIn Public Jobs ──────────────────────────────────────────────────────
def scrape_linkedin(
    keywords: list[str],
    location: str = "India",
    job_type: str = "internship",
    pages: int = 2,
) -> list[dict]:
    """
    Scrape LinkedIn public job listings (no login required).
    LinkedIn's public API returns JSON-LD data embedded in the page.
    """
    BASE = "https://www.linkedin.com/jobs/search"
    session = _session()
    all_jobs: dict[str, dict] = {}

    for keyword in keywords:
        for start in range(0, pages * 25, 25):
            params = {
                "keywords": keyword,
                "location": location,
                "f_JT":     "I" if job_type == "internship" else "",
                "start":    start,
            }
            resp = _safe_get(session, BASE, params=params)
            if not resp:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".job-search-card") or soup.select("[data-entity-urn]")

            if not cards:
                logger.info("[LinkedIn] No cards found for '%s' start=%d", keyword, start)
                break

            for card in cards:
                try:
                    title_el   = card.select_one("h3.base-search-card__title")
                    company_el = card.select_one("h4.base-search-card__subtitle a") \
                                 or card.select_one("h4.base-search-card__subtitle")
                    loc_el     = card.select_one(".job-search-card__location")
                    link_el    = card.select_one("a.base-card__full-link") \
                                 or card.select_one("a[href*='linkedin.com/jobs']")

                    if not title_el or not link_el:
                        continue

                    url = link_el["href"].split("?")[0]   # strip tracking params
                    job = {
                        "job_id":     _job_id("linkedin", url),
                        "source":     "linkedin",
                        "title":      title_el.get_text(strip=True),
                        "company":    company_el.get_text(strip=True) if company_el else "Unknown",
                        "location":   loc_el.get_text(strip=True) if loc_el else "India",
                        "duration":   None,
                        "stipend":    None,
                        "url":        url,
                        "tags":       [keyword.lower()],
                        "description": "",
                        "scraped_at": datetime.now().isoformat(),
                    }
                    all_jobs.setdefault(job["job_id"], job)
                except Exception as e:
                    logger.debug("LinkedIn card error: %s", e)

            time.sleep(DELAY)

    logger.info("[LinkedIn] %d unique listings", len(all_jobs))
    return list(all_jobs.values())


# ── Unstop (Hackerearth-style competitions + jobs) ────────────────────────────
def scrape_unstop(
    keywords: list[str],
    pages: int = 2,
) -> list[dict]:
    """
    Scrape Unstop (formerly Dare2Compete) for hackathons, challenges, internships.
    """
    BASE    = "https://unstop.com/api/public/opportunity/search-result"
    session = _session()
    all_jobs: dict[str, dict] = {}

    for keyword in keywords:
        for page in range(1, pages + 1):
            params = {
                "opportunity":      "internship,hackathon,competition",
                "search":           keyword,
                "page":             page,
                "per_page":         20,
                "supernovaCategories": "",
            }
            try:
                resp = session.get(BASE, params=params, timeout=TIMEOUT)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                items = data.get("data", {}).get("data", []) or []

                for item in items:
                    title   = item.get("title") or item.get("name", "")
                    company = item.get("organisation", {}).get("name", "Unknown")
                    url     = f"https://unstop.com/{item.get('public_url', '')}"
                    tags    = [t.get("name", "") for t in item.get("skills", [])]
                    stipend = item.get("prize_money") or item.get("stipend_range")

                    job = {
                        "job_id":      _job_id("unstop", url),
                        "source":      "unstop",
                        "title":       title,
                        "company":     company,
                        "location":    item.get("eligible_regions", "India"),
                        "duration":    item.get("duration"),
                        "stipend":     str(stipend) if stipend else None,
                        "url":         url,
                        "tags":        [t.lower() for t in tags if t],
                        "description": item.get("short_description", "")[:1500],
                        "scraped_at":  datetime.now().isoformat(),
                    }
                    all_jobs.setdefault(job["job_id"], job)

            except Exception as e:
                logger.warning("[Unstop] Error for '%s' page %d: %s", keyword, page, e)
            time.sleep(DELAY)

    logger.info("[Unstop] %d unique listings", len(all_jobs))
    return list(all_jobs.values())


# ── Wellfound / AngelList (startup jobs) ─────────────────────────────────────
def scrape_wellfound(
    roles: Optional[list[str]] = None,
    pages: int = 1,
) -> list[dict]:
    """
    Scrape Wellfound for startup internships and fresher roles.
    """
    if roles is None:
        roles = ["software-engineer", "data-scientist", "machine-learning"]

    BASE    = "https://wellfound.com/jobs"
    session = _session()
    all_jobs: dict[str, dict] = {}

    for role in roles:
        url  = f"{BASE}?role={role}&job_type=internship&remote=true"
        resp = _safe_get(session, url)
        if not resp:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("[data-test='JobListing']") or soup.select(".job-listing")

        for card in cards:
            try:
                title_el   = card.select_one("h2") or card.select_one(".job-name")
                company_el = card.select_one(".company-name") or card.select_one("h3")
                link_el    = card.select_one("a[href*='/jobs/']")

                if not title_el or not link_el:
                    continue

                href = link_el["href"]
                job_url = href if href.startswith("http") else "https://wellfound.com" + href

                job = {
                    "job_id":     _job_id("wellfound", job_url),
                    "source":     "wellfound",
                    "title":      title_el.get_text(strip=True),
                    "company":    company_el.get_text(strip=True) if company_el else "Startup",
                    "location":   "Remote / Global",
                    "duration":   None,
                    "stipend":    None,
                    "url":        job_url,
                    "tags":       [role.replace("-", " ")],
                    "description": "",
                    "scraped_at": datetime.now().isoformat(),
                }
                all_jobs.setdefault(job["job_id"], job)
            except Exception as e:
                logger.debug("Wellfound card error: %s", e)

        time.sleep(DELAY)

    logger.info("[Wellfound] %d unique listings", len(all_jobs))
    return list(all_jobs.values())


# ── Public entry point ────────────────────────────────────────────────────────
def scrape_all(
    keywords: Optional[list[str]] = None,
    enable_linkedin:  bool = True,
    enable_unstop:    bool = True,
    enable_wellfound: bool = True,
) -> list[dict]:
    """
    Run all enabled scrapers and merge results (deduplicated by job_id+source).
    """
    if keywords is None:
        keywords = ["python", "machine learning", "web development", "data science"]

    combined: dict[str, dict] = {}

    def _merge(jobs: list[dict]):
        for j in jobs:
            key = f"{j['source']}:{j['job_id']}"
            combined.setdefault(key, j)

    if enable_linkedin:
        _merge(scrape_linkedin(keywords))
    if enable_unstop:
        _merge(scrape_unstop(keywords))
    if enable_wellfound:
        _merge(scrape_wellfound())

    result = list(combined.values())
    logger.info("[CompanyScraper] Total merged listings: %d", len(result))
    return result


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    jobs = scrape_unstop(["python", "machine learning"], pages=1)
    print(f"Found {len(jobs)} jobs")
    if jobs:
        print(json.dumps(jobs[0], indent=2))
