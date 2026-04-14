"""
Devfolio scraper — hackathons for developers
"""
import requests
import time
from datetime import datetime
from typing import Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

GRAPHQL_URL = "https://api.devfolio.co/api/hackathons"


def scrape_devfolio(keywords: Optional[list] = None, pages: int = 3) -> list[dict]:
    """
    Scrape Devfolio for open hackathons.
    """
    jobs = []
    seen = set()

    try:
        for page in range(1, pages + 1):
            params = {
                "page": page,
                "per_page": 20,
                "status": "open",
                "type": "online",
            }
            resp = requests.get(GRAPHQL_URL, headers=HEADERS, params=params, timeout=10)
            if resp.status_code != 200:
                # Try alternate endpoint
                break

            data = resp.json()
            items = data if isinstance(data, list) else data.get("results", data.get("hackathons", []))

            if not items:
                break

            for item in items:
                uid = str(item.get("id", item.get("slug", "")))
                if uid in seen:
                    continue
                seen.add(uid)

                slug = item.get("slug", uid)
                title = item.get("name", item.get("title", "Hackathon"))
                company = item.get("organization", {})
                if isinstance(company, dict):
                    company = company.get("name", "Devfolio")
                elif not company:
                    company = "Devfolio"

                prize = item.get("prize_amount", 0)
                stipend = f"₹{prize:,}" if prize and prize > 0 else "Prizes available"

                desc = item.get("tagline", "") or item.get("description", "")
                if not desc:
                    desc = f"Hackathon: {title}. Join on Devfolio."

                jobs.append({
                    "job_id": f"devfolio_{uid}",
                    "source": "devfolio",
                    "title": f"{title} Hackathon",
                    "company": company if isinstance(company, str) else "Devfolio",
                    "location": "Online",
                    "duration": "",
                    "stipend": stipend,
                    "url": f"https://devfolio.co/hackathons/{slug}",
                    "tags": item.get("themes", []) or item.get("tracks", []) or [],
                    "description": str(desc)[:500],
                    "scraped_at": datetime.now().isoformat(),
                })

            time.sleep(0.5)
            if len(items) < 20:
                break

    except Exception as e:
        print(f"[Devfolio] Error: {e}")

    # Fallback: scrape public hackathons page
    if not jobs:
        jobs = _scrape_devfolio_fallback()

    print(f"[Devfolio] Scraped {len(jobs)} hackathons")
    return jobs


def _scrape_devfolio_fallback() -> list[dict]:
    """Fallback using BeautifulSoup if API fails"""
    try:
        from bs4 import BeautifulSoup
        resp = requests.get("https://devfolio.co/hackathons", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=10)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        jobs = []
        cards = soup.select("[class*='HackathonCard'], [class*='hackathon-card'], article")

        for card in cards[:20]:
            title_el = card.select_one("h2, h3, [class*='title'], [class*='name']")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = card.select_one("a")
            url = link["href"] if link else "https://devfolio.co/hackathons"
            if not url.startswith("http"):
                url = f"https://devfolio.co{url}"

            jobs.append({
                "job_id": f"devfolio_{hash(title)}",
                "source": "devfolio",
                "title": f"{title} Hackathon",
                "company": "Devfolio",
                "location": "Online",
                "duration": "",
                "stipend": "Prizes available",
                "url": url,
                "tags": [],
                "description": f"Hackathon: {title}. Register on Devfolio.",
                "scraped_at": datetime.now().isoformat(),
            })
        return jobs
    except Exception as e:
        print(f"[Devfolio fallback] {e}")
        return []


if __name__ == "__main__":
    jobs = scrape_devfolio()
    for j in jobs[:3]:
        print(j["title"], "|", j["url"])
