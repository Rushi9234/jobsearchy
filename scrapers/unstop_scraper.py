"""
Unstop scraper — hackathons, competitions, jobs
"""
import requests
import time
from datetime import datetime
from typing import Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://unstop.com/",
    "Origin": "https://unstop.com",
}

BASE_URL = "https://unstop.com/api/public/opportunity/search-result"


def scrape_unstop(keywords: Optional[list] = None, pages: int = 3) -> list[dict]:
    """
    Scrape Unstop for hackathons and competitions.
    Returns list of job dicts compatible with JobSearcher DB.
    """
    jobs = []
    seen = set()

    search_terms = keywords[:3] if keywords else ["python", "machine learning", "data science"]
    # Also always search for general hackathons
    search_terms += ["hackathon", "competition"]

    for term in search_terms:
        for page in range(1, pages + 1):
            try:
                params = {
                    "search": term,
                    "page": page,
                    "size": 20,
                    "oppstatus": "open",
                    "type": "hackathon,competition,job,internship",
                }
                resp = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=10)
                if resp.status_code != 200:
                    break

                data = resp.json()
                items = data.get("data", {}).get("data", [])
                if not items:
                    break

                for item in items:
                    uid = str(item.get("id", ""))
                    if uid in seen:
                        continue
                    seen.add(uid)

                    title = item.get("title", "") or item.get("name", "")
                    org = item.get("organisation", {})
                    company = org.get("name", "") if isinstance(org, dict) else ""
                    url = f"https://unstop.com/{item.get('public_url', '')}"
                    opp_type = item.get("type", "hackathon")

                    # Prize/stipend
                    prize = item.get("prizes", "") or item.get("stipend", "")
                    if isinstance(prize, (int, float)) and prize > 0:
                        stipend = f"₹{prize:,}"
                    elif isinstance(prize, str) and prize:
                        stipend = prize
                    else:
                        stipend = ""

                    jobs.append({
                        "job_id": f"unstop_{uid}",
                        "source": "unstop",
                        "title": title,
                        "company": company,
                        "location": item.get("location", "Online"),
                        "duration": "",
                        "stipend": stipend,
                        "url": url,
                        "tags": item.get("skills", []) or [],
                        "description": item.get("description", "")[:500] if item.get("description") else f"{opp_type.title()} on Unstop. {title}",
                        "scraped_at": datetime.now().isoformat(),
                    })

                time.sleep(0.5)

            except Exception as e:
                print(f"[Unstop] Error on page {page} term '{term}': {e}")
                break

    print(f"[Unstop] Scraped {len(jobs)} listings")
    return jobs


if __name__ == "__main__":
    jobs = scrape_unstop(keywords=["python", "machine learning"])
    for j in jobs[:3]:
        print(j["title"], "|", j["company"], "|", j["url"])
