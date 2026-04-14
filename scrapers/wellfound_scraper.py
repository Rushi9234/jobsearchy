"""
Wellfound (AngelList) scraper — startup jobs via public API
"""
import requests
import time
from datetime import datetime
from typing import Optional


def scrape_wellfound(keywords: Optional[list] = None, pages: int = 2) -> list[dict]:
    """Scrape Wellfound startup jobs via their public search API."""
    jobs = []
    seen = set()

    search_terms = keywords[:3] if keywords else ["python", "data science", "machine learning"]

    # Try Wellfound public API endpoints
    for term in search_terms:
        try:
            # Wellfound has a JSON API for job search
            url = "https://wellfound.com/api/jobs"
            params = {
                "query": term,
                "remote": "true",
                "job_type": "internship",
                "page": 1,
            }
            resp = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://wellfound.com/jobs",
            }, params=params, timeout=10)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    items = data.get("jobs", data.get("results", []))
                    for item in items[:15]:
                        uid = str(item.get("id", abs(hash(str(item)))))
                        if uid in seen: continue
                        seen.add(uid)
                        title = item.get("title", item.get("role", ""))
                        company = item.get("startup", {})
                        if isinstance(company, dict):
                            company = company.get("name", "Startup")
                        job_url = item.get("url", item.get("apply_url", "https://wellfound.com/jobs"))
                        if not job_url.startswith("http"):
                            job_url = f"https://wellfound.com{job_url}"
                        jobs.append({
                            "job_id": f"wellfound_{uid}",
                            "source": "wellfound",
                            "title": title,
                            "company": company,
                            "location": item.get("location", "Remote / India"),
                            "duration": "",
                            "stipend": item.get("compensation", ""),
                            "url": job_url,
                            "tags": [term.lower()],
                            "description": item.get("description", f"Startup role: {title} at {company}.")[:500],
                            "scraped_at": datetime.now().isoformat(),
                        })
                    if jobs:
                        time.sleep(1)
                        continue
                except Exception:
                    pass

            # Fallback: try AngelList talent API
            angel_url = f"https://api.angel.co/1/jobs?job_types[]=internship&skills[]={term.replace(" ","+")}"
            resp2 = requests.get(angel_url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            }, timeout=10)
            if resp2.status_code == 200:
                try:
                    data2 = resp2.json()
                    for item in data2.get("jobs", [])[:10]:
                        uid = str(item.get("id", abs(hash(str(item)))))
                        if uid in seen: continue
                        seen.add(uid)
                        startup = item.get("startup", {})
                        jobs.append({
                            "job_id": f"wellfound_{uid}",
                            "source": "wellfound",
                            "title": item.get("title", "Startup Role"),
                            "company": startup.get("name", "Startup") if isinstance(startup, dict) else "Startup",
                            "location": item.get("remote_ok", False) and "Remote" or "India",
                            "duration": "",
                            "stipend": "",
                            "url": item.get("url", "https://wellfound.com/jobs"),
                            "tags": [s.get("name","").lower() for s in item.get("skills", [])],
                            "description": item.get("description", "")[:500],
                            "scraped_at": datetime.now().isoformat(),
                        })
                except Exception:
                    pass

        except Exception as e:
            print(f"[Wellfound] Error for '{term}': {e}")

        time.sleep(1)

    print(f"[Wellfound] Scraped {len(jobs)} listings")
    return jobs


if __name__ == "__main__":
    jobs = scrape_wellfound(keywords=["python", "machine learning"])
    for j in jobs[:3]:
        print(j["title"], "|", j["company"], "|", j["url"])
