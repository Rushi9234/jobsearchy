"""
naukri_scraper.py — Searchy Naukri Scraper
Uses Naukri's public search API with correct headers.
"""
import requests
import time
import json
from datetime import datetime
from typing import Optional

# Strategy 1: Naukri v3 API
HEADERS_V3 = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.naukri.com/",
    "Origin": "https://www.naukri.com",
    "appid": "109",
    "systemcountrycode": "IN",
    "clientid": "d3skt0p",
    "gid": "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
    "Content-Type": "application/json",
}

# Strategy 2: Naukri public HTML scrape
HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.naukri.com/",
}


def _parse_html_jobs(html: str, keyword: str) -> list[dict]:
    """Parse Naukri HTML page for job listings."""
    from bs4 import BeautifulSoup
    import hashlib
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    # Naukri uses article tags or div.jobTuple
    cards = (soup.select("article.jobTuple") or
             soup.select(".jobTupleHeader") or
             soup.select("[class*='job-tuple']") or
             soup.select(".srp-jobtuple-wrapper"))

    for card in cards:
        try:
            title_el   = (card.select_one("a.title") or
                          card.select_one(".jobTitle") or
                          card.select_one("a[title]"))
            company_el = (card.select_one(".companyInfo a") or
                          card.select_one(".comp-name") or
                          card.select_one("[class*='company']"))
            loc_el     = (card.select_one(".locWdth") or
                          card.select_one(".location") or
                          card.select_one("[class*='location']"))

            if not title_el:
                continue

            title   = title_el.get_text(strip=True)
            company = company_el.get_text(strip=True) if company_el else "Company"
            location= loc_el.get_text(strip=True) if loc_el else "India"
            href    = title_el.get("href", "")
            url     = href if href.startswith("http") else f"https://www.naukri.com{href}"
            uid     = hashlib.md5(url.encode()).hexdigest()[:10]

            jobs.append({
                "job_id":      f"naukri_{uid}",
                "source":      "naukri",
                "title":       title,
                "company":     company,
                "location":    location,
                "duration":    "",
                "stipend":     "",
                "url":         url,
                "tags":        [keyword.lower(), "fresher", "india"],
                "description": f"{title} at {company}. Location: {location}. Entry level role.",
                "scraped_at":  datetime.now().isoformat(),
            })
        except Exception as e:
            continue

    return jobs


def _try_naukri_api(term: str, seen: set) -> list[dict]:
    """Try Naukri v3 JSON API."""
    jobs = []
    try:
        # Try v3 search
        params = {
            "noOfResults": 20,
            "urlType": "search_by_keyword",
            "searchType": "adv",
            "keyword": term,
            "pageNo": 1,
            "experience": 0,
            "k": term,
            "location": "",
            "l": "",
        }
        resp = requests.get(
            "https://www.naukri.com/jobapi/v3/search",
            headers=HEADERS_V3,
            params=params,
            timeout=12
        )
        if resp.status_code == 200:
            data = resp.json()
            listings = data.get("jobDetails", [])
            for item in listings:
                if not isinstance(item, dict):
                    continue
                uid = str(item.get("jobId", item.get("id", "")))
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                title = item.get("title", "")
                if not title:
                    continue
                company = item.get("companyName", "Company")
                placeholders = item.get("placeholders", [])
                location = "India"
                for ph in placeholders:
                    if isinstance(ph, dict) and ph.get("type") == "location":
                        location = ph.get("label", "India")
                        break
                salary  = item.get("salary", "")
                desc    = item.get("jobDescription", "")[:500] if item.get("jobDescription") else f"{title} at {company}."
                jd_url  = item.get("jdURL", "")
                job_url = f"https://www.naukri.com{jd_url}" if jd_url and not jd_url.startswith("http") else (jd_url or "https://www.naukri.com")
                tags_raw = item.get("tagsAndSkills", "")
                if isinstance(tags_raw, str):
                    tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
                else:
                    tags = list(tags_raw) if tags_raw else []

                jobs.append({
                    "job_id":      f"naukri_{uid}",
                    "source":      "naukri",
                    "title":       title,
                    "company":     company,
                    "location":    location,
                    "duration":    "",
                    "stipend":     salary,
                    "url":         job_url,
                    "tags":        tags,
                    "description": desc,
                    "scraped_at":  datetime.now().isoformat(),
                })
    except Exception as e:
        print(f"[Naukri API] Error for '{term}': {e}")
    return jobs


def _try_naukri_html(term: str, seen: set) -> list[dict]:
    """Fallback: scrape Naukri HTML search page."""
    jobs = []
    try:
        slug = term.replace(" ", "-").lower()
        url  = f"https://www.naukri.com/{slug}-jobs"
        resp = requests.get(url, headers=HEADERS_HTML, timeout=15)
        if resp.status_code == 200:
            parsed = _parse_html_jobs(resp.text, term)
            for j in parsed:
                if j["job_id"] not in seen:
                    seen.add(j["job_id"])
                    jobs.append(j)
        # Also try search URL format
        search_url = f"https://www.naukri.com/jobs-in-india?k={term.replace(' ', '%20')}&experience=0"
        resp2 = requests.get(search_url, headers=HEADERS_HTML, timeout=15)
        if resp2.status_code == 200:
            parsed2 = _parse_html_jobs(resp2.text, term)
            for j in parsed2:
                if j["job_id"] not in seen:
                    seen.add(j["job_id"])
                    jobs.append(j)
    except Exception as e:
        print(f"[Naukri HTML] Error for '{term}': {e}")
    return jobs


def _try_naukri_campus(term: str, seen: set) -> list[dict]:
    """Try Naukri Campus API — specifically for freshers/interns."""
    jobs = []
    try:
        resp = requests.get(
            "https://campus.naukri.com/api/jobsearch/v2/search",
            headers={**HEADERS_V3, "Referer": "https://campus.naukri.com/"},
            params={
                "noOfResults": 20,
                "keyword": term,
                "pageNo": 1,
                "experience": 0,
            },
            timeout=12
        )
        if resp.status_code == 200:
            data = resp.json()
            listings = data.get("jobDetails", data.get("results", []))
            for item in listings:
                if not isinstance(item, dict):
                    continue
                uid = str(item.get("jobId", item.get("id", "")))
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                title = item.get("title", item.get("jobTitle", ""))
                if not title:
                    continue
                company = item.get("companyName", item.get("company", "Company"))
                location = item.get("location", "India")
                jd_url = item.get("jdURL", item.get("url", ""))
                job_url = f"https://campus.naukri.com{jd_url}" if jd_url and not jd_url.startswith("http") else (jd_url or "https://campus.naukri.com")

                jobs.append({
                    "job_id":      f"naukri_campus_{uid}",
                    "source":      "naukri",
                    "title":       title,
                    "company":     company,
                    "location":    location,
                    "duration":    "",
                    "stipend":     item.get("salary", ""),
                    "url":         job_url,
                    "tags":        [term.lower(), "fresher", "campus"],
                    "description": item.get("jobDescription", f"{title} at {company}.")[:500],
                    "scraped_at":  datetime.now().isoformat(),
                })
    except Exception as e:
        print(f"[Naukri Campus] Error for '{term}': {e}")
    return jobs


# INACTIVE / DEPRECATED: Preserved in codebase for future adapter updates.
# Currently inactive because campus.naukri.com DNS is dead and public HTML triggers Akamai bot blocks.
ENABLED = False


def scrape_naukri(keywords: Optional[list] = None, pages: int = 1) -> list[dict]:
    """Scrape Naukri using 3-strategy fallback (currently inactive)."""
    if not ENABLED:
        return []

    jobs = []
    seen = set()

    search_terms = keywords[:5] if keywords else []
    # Always include these fresher-focused terms
    fresher_terms = [
        "data analyst fresher",
        "data science intern",
        "python developer fresher",
        "machine learning intern",
        "research analyst fresher",
        "business analyst intern",
        "data engineer fresher",
    ]
    all_terms = list(dict.fromkeys(search_terms + fresher_terms))  # dedupe, preserve order

    for term in all_terms:
        # Strategy 1: v3 API
        found = _try_naukri_api(term, seen)
        if found:
            jobs.extend(found)
            time.sleep(0.5)
            continue

        # Strategy 2: Campus API
        found = _try_naukri_campus(term, seen)
        if found:
            jobs.extend(found)
            time.sleep(0.5)
            continue

        # Strategy 3: HTML scrape
        found = _try_naukri_html(term, seen)
        jobs.extend(found)
        time.sleep(1.0)

    print(f"[Naukri] Scraped {len(jobs)} listings")
    return jobs

scrape = scrape_naukri


if __name__ == "__main__":
    jobs = scrape_naukri(keywords=["python", "data science", "machine learning"])
    print(f"Total: {len(jobs)}")
    for j in jobs[:5]:
        print(f"  {j['title']} | {j['company']} | {j['location']}")
