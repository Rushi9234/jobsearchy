"""
internshala_scraper.py — Searchy Internshala Scraper
Selectors verified against live Internshala HTML (April 2026).
"""

import time
import hashlib
import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://internshala.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://internshala.com/",
}
REQUEST_DELAY = 2.0
TIMEOUT = 15


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(BASE_URL + "/internships/", timeout=TIMEOUT)
        time.sleep(1)
    except Exception:
        pass
    return s


def _job_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _safe_get(session, url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                time.sleep(10 * attempt)
        except requests.RequestException as e:
            logger.warning("Request error: %s", e)
            time.sleep(REQUEST_DELAY)
    return None


def _parse_html_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".internship_meta")
    jobs = []

    for card in cards:
        try:
            # Title — verified selector
            title_el = card.select_one(".job-internship-name a") or card.select_one("h2 a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)

            # URL — verified selector
            href = title_el.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else BASE_URL + href

            # Company — verified selector
            company_el = card.select_one(".company-name") or card.select_one(".company_name")
            company = company_el.get_text(strip=True) if company_el else "Unknown"

            # Location — verified selector
            loc_el = card.select_one(".locations span") or card.select_one(".row-1-item.locations span")
            location = loc_el.get_text(strip=True) if loc_el else "India"
            if "work from home" in location.lower() or "wfh" in location.lower():
                location = "Remote"

            # Stipend — verified selector
            stip_el = card.select_one(".stipend")
            stipend = stip_el.get_text(strip=True) if stip_el else "Not specified"

            # Duration — 3rd row-1-item span (location, stipend, duration order)
            row_items = card.select(".row-1-item span")
            # Duration — dedicated calendar icon div
            duration = None
            for item in card.select(".row-1-item"):
                if item.select_one(".ic-16-calendar"):
                    duration = item.get_text(strip=True)
                    break

            # Description snippet from about_job
            desc_el = card.select_one(".about_job .text") or card.select_one(".about_job")
            description_snippet = desc_el.get_text(separator=" ", strip=True)[:500] if desc_el else ""

            # Build full description for scoring
            description = f"{title} internship at {company}. {description_snippet} Location: {location}. Stipend: {stipend}."

            # Tags from skills section
            skill_els = card.select(".round_tabs") or card.select(".skill-tag")
            tags = [el.get_text(strip=True).lower() for el in skill_els if el.get_text(strip=True)]

            jobs.append({
                "job_id":     _job_id(url),
                "source":     "internshala",
                "title":      title,
                "company":    company,
                "location":   location,
                "duration":   duration,
                "stipend":    stipend,
                "url":        url,
                "tags":       tags,
                "description": description,
                "scraped_at": datetime.now().isoformat(),
            })

        except Exception as e:
            logger.debug("Card parse error: %s", e)

    return jobs


def scrape_keyword(session, keyword: str, pages: int = 2, fetch_details: bool = False) -> list[dict]:
    jobs = []
    keyword_slug = keyword.replace(" ", "-").lower()

    for page in range(1, pages + 1):
        if page == 1:
            url = f"{BASE_URL}/internships/keywords-{keyword_slug}"
        else:
            url = f"{BASE_URL}/internships/keywords-{keyword_slug}/page-{page}"

        logger.info("[Internshala] Scraping '%s' page %d", keyword, page)
        resp = _safe_get(session, url)
        if not resp:
            break

        page_jobs = _parse_html_cards(resp.text)
        logger.info("  Found %d listings on page %d", len(page_jobs), page)

        if not page_jobs:
            break

        jobs.extend(page_jobs)
        time.sleep(REQUEST_DELAY)

    return jobs


def scrape(keywords=None, pages_per_keyword: int = 2, fetch_details: bool = False) -> list[dict]:
    if keywords is None:
        keywords = [
            "python", "machine learning", "data science",
            "web development", "react", "flask", "nlp", "ai", "data analytics"
        ]

    session = _session()
    all_jobs: dict[str, dict] = {}

    for keyword in keywords:
        try:
            jobs = scrape_keyword(session, keyword, pages=pages_per_keyword, fetch_details=fetch_details)
            for job in jobs:
                all_jobs.setdefault(job["job_id"], job)
        except Exception as e:
            logger.error("[Internshala] Error scraping '%s': %s", keyword, e)

    result = list(all_jobs.values())
    logger.info("[Internshala] Total unique listings: %d", len(result))
    return result


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    session = _session()
    url = f"{BASE_URL}/internships/keywords-python"
    print(f"Testing: {url}")
    resp = _safe_get(session, url)
    if resp:
        soup = BeautifulSoup(resp.text, "html.parser")
        print("Cards found:", len(soup.select(".internship_meta")))
        jobs = _parse_html_cards(resp.text)
        print(f"Parsed jobs: {len(jobs)}")
        if jobs:
            print(json.dumps(jobs[0], indent=2))
        else:
            print("Still 0 — check selectors")
