"""
HackerEarth scraper — hackathons and challenges
Uses the public challenges page + JSON endpoint fallback.
"""
import hashlib
import requests
import time
from datetime import datetime
from typing import Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def scrape_hackerearth(keywords: Optional[list] = None) -> list[dict]:
    """Scrape HackerEarth for open hackathons and challenges."""
    jobs = []
    seen = set()

    # Strategy 1: Try the hackathon listings page (most reliable)
    try:
        from bs4 import BeautifulSoup
        urls_to_try = [
            "https://www.hackerearth.com/challenges/hackathon/",
            "https://www.hackerearth.com/challenges/",
        ]
        for url in urls_to_try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")

            # Try multiple card selectors
            cards = (
                soup.select(".challenge-card-modern") or
                soup.select(".challenge-tile") or
                soup.select("[class*='challenge'][class*='card']") or
                soup.select("article.challenge") or
                soup.select(".upcoming-challenges .challenge") or
                soup.select("[data-event-id]")
            )

            for card in cards[:20]:
                title_el = (
                    card.select_one("h2") or card.select_one("h3") or
                    card.select_one(".title") or card.select_one("[class*='title']") or
                    card.select_one("a")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 3:
                    continue

                link = card.select_one("a[href]")
                href = link["href"] if link else ""
                job_url = href if href.startswith("http") else f"https://www.hackerearth.com{href}"

                uid = hashlib.md5((title + job_url).encode()).hexdigest()[:12]
                if uid in seen:
                    continue
                seen.add(uid)

                prize_el = card.select_one("[class*='prize'], [class*='reward']")
                prize = prize_el.get_text(strip=True) if prize_el else "Prizes available"

                jobs.append({
                    "job_id": f"he_{uid}",
                    "source": "hackerearth",
                    "title": title,
                    "company": "HackerEarth",
                    "location": "Online",
                    "duration": "",
                    "stipend": prize,
                    "url": job_url,
                    "tags": [],
                    "description": f"Hackathon/Challenge on HackerEarth: {title}. Register and compete for prizes.",
                    "scraped_at": datetime.now().isoformat(),
                })

            if jobs:
                break  # Stop if we got results
    except Exception as e:
        print(f"[HackerEarth] Page scrape error: {e}")

    # Strategy 2: Try their internal API (new endpoint)
    if not jobs:
        try:
            api_urls = [
                "https://www.hackerearth.com/graphql/",
                "https://api.hackerearth.com/v4/events/",
            ]
            for api_url in api_urls:
                resp = requests.get(api_url, headers={**HEADERS, "Accept": "application/json"}, timeout=10)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        items = data.get("data", data if isinstance(data, list) else [])
                        for item in (items[:15] if isinstance(items, list) else []):
                            title = item.get("title", item.get("name", ""))
                            if not title:
                                continue
                            raw_id = str(item.get("id") or "")
                            uid = raw_id if raw_id else hashlib.md5(title.encode()).hexdigest()[:12]
                            if uid in seen:
                                continue
                            seen.add(uid)
                            url = item.get("url", item.get("challenge_url", "https://www.hackerearth.com/challenges/"))
                            jobs.append({
                                "job_id": f"he_{uid}",
                                "source": "hackerearth",
                                "title": title,
                                "company": "HackerEarth",
                                "location": "Online",
                                "duration": "",
                                "stipend": str(item.get("prize", "Prizes available")),
                                "url": url if url.startswith("http") else f"https://www.hackerearth.com{url}",
                                "tags": item.get("skills", []) or [],
                                "description": item.get("description", f"Challenge: {title}")[:500],
                                "scraped_at": datetime.now().isoformat(),
                            })
                        if jobs:
                            break
                    except Exception:
                        pass
        except Exception as e:
            print(f"[HackerEarth] API error: {e}")

    if not jobs:
        print("[HackerEarth] No active hackathons found on this scan.")

    print(f"[HackerEarth] Scraped {len(jobs)} listings")
    return jobs


if __name__ == "__main__":
    jobs = scrape_hackerearth()
    for j in jobs[:3]:
        print(j["title"], "|", j["url"])
