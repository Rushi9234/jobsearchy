"""
govt_scraper.py — Searchy Government Jobs & Internships Scraper
Sources:
  - Internshala (govt, PSU, research, public-policy categories)
  - Naukri (govt sector jobs)
  - LinkedIn (government jobs India)
  - Unstop (govt challenges + PSU competitions)
  - Static high-value portals (AICTE, ISRO, DRDO, NITI, PM Internship, RBI, SEBI, NABARD, etc.)
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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY   = 2.0
TIMEOUT = 15


def _job_id(source: str, key: str) -> str:
    return f"{source}_{hashlib.md5(key.encode()).hexdigest()[:10]}"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _safe_get(session, url: str, params: dict = None, retries: int = 3) -> Optional[requests.Response]:
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                time.sleep(8 * attempt)
            elif r.status_code in (403, 404):
                logger.debug("HTTP %d for %s", r.status_code, url)
                return None
        except requests.RequestException as e:
            logger.warning("Request error: %s", e)
            time.sleep(DELAY)
    return None


# ── 1. Internshala — govt / PSU / research / policy categories ───────────────
def _scrape_internshala_govt(session) -> list[dict]:
    jobs = []
    seen = set()

    # All govt-adjacent category slugs on Internshala
    categories = [
        "government-internship",
        "public-policy-internship",
        "research-internship",
        "data-science-internship",
        "economics-internship",
        "finance-internship",
        "statistics-internship",
        "psu-internship",
        "ngo-internship",
        "social-work-internship",
    ]
    # Also keyword-based pages for govt roles
    keywords = [
        "government", "psu", "public sector", "niti aayog",
        "policy research", "social research", "economics research",
        "data analyst government", "upsc", "civil services",
    ]

    # Category pages
    for cat in categories:
        for page in range(1, 4):
            url = f"https://internshala.com/internships/{cat}"
            if page > 1:
                url += f"/page-{page}"
            resp = _safe_get(session, url)
            if not resp:
                break
            parsed = _parse_internshala_cards(resp.text, "govt_internshala")
            new = [j for j in parsed if j["job_id"] not in seen]
            seen.update(j["job_id"] for j in new)
            jobs.extend(new)
            if len(parsed) < 5:
                break
            time.sleep(DELAY)

    # Keyword pages
    for kw in keywords:
        slug = kw.replace(" ", "-").lower()
        url = f"https://internshala.com/internships/keywords-{slug}"
        resp = _safe_get(session, url)
        if not resp:
            continue
        parsed = _parse_internshala_cards(resp.text, "govt_internshala")
        new = [j for j in parsed if j["job_id"] not in seen]
        seen.update(j["job_id"] for j in new)
        jobs.extend(new)
        time.sleep(DELAY)

    logger.info("[Internshala Govt] %d listings", len(jobs))
    return jobs


def _parse_internshala_cards(html: str, source: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".internship_meta")
    jobs = []
    for card in cards:
        try:
            title_el   = card.select_one(".job-internship-name a") or card.select_one("h2 a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href  = title_el.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else "https://internshala.com" + href

            company_el = card.select_one(".company-name")
            company    = company_el.get_text(strip=True) if company_el else "Organisation"

            loc_el   = card.select_one(".locations span")
            location = loc_el.get_text(strip=True) if loc_el else "India"
            if "work from home" in location.lower():
                location = "Remote"

            stip_el = card.select_one(".stipend")
            stipend = stip_el.get_text(strip=True) if stip_el else "Unpaid / As per policy"

            dur = None
            for item in card.select(".row-1-item"):
                if item.select_one(".ic-16-calendar"):
                    dur = item.get_text(strip=True)
                    break

            desc_el = card.select_one(".about_job .text") or card.select_one(".about_job")
            snippet = desc_el.get_text(separator=" ", strip=True)[:400] if desc_el else ""
            description = f"{title} at {company}. {snippet} Location: {location}. Stipend: {stipend}."

            skill_els = card.select(".round_tabs") or card.select(".skill-tag")
            tags = [el.get_text(strip=True).lower() for el in skill_els if el.get_text(strip=True)]
            tags += ["internship", "india"]

            jobs.append({
                "job_id":      _job_id(source, url),
                "source":      source,
                "title":       title,
                "company":     company,
                "location":    location,
                "duration":    dur,
                "stipend":     stipend,
                "url":         url,
                "tags":        tags,
                "description": description,
                "scraped_at":  datetime.now().isoformat(),
            })
        except Exception as e:
            logger.debug("Card parse error: %s", e)
    return jobs


# ── 2. Naukri — government sector jobs ───────────────────────────────────────
def _scrape_naukri_govt(session) -> list[dict]:
    jobs = []
    seen = set()

    NAUKRI_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.naukri.com/",
        "Origin": "https://www.naukri.com",
        "appid": "109",
        "systemcountrycode": "IN",
        "clientid": "d3skt0p",
        "gid": "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
    }

    search_terms = [
        "government data analyst",
        "psu data science",
        "government research analyst",
        "public sector python",
        "government statistics",
        "UPSC data",
        "government internship fresher",
        "psu engineer fresher",
        "government IT officer",
        "sarkari naukri data",
    ]

    for term in search_terms:
        try:
            params = {
                "noOfResults": 20,
                "urlType": "search_by_keyword",
                "searchType": "adv",
                "keyword": term,
                "pageNo": 1,
                "experience": 0,
                "k": term,
                "location": "",
            }
            resp = requests.get(
                "https://www.naukri.com/jobapi/v3/search",
                headers=NAUKRI_HEADERS,
                params=params,
                timeout=12
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            listings = data.get("jobDetails", [])

            for item in listings:
                if not isinstance(item, dict):
                    continue
                uid = str(item.get("jobId", item.get("id", "")))
                if not uid or uid in seen:
                    continue
                seen.add(uid)

                title   = item.get("title", "")
                if not title:
                    continue
                company = item.get("companyName", "Government")
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
                elif isinstance(tags_raw, list):
                    tags = [t.lower() for t in tags_raw]
                else:
                    tags = []
                tags += ["government", "india"]

                jobs.append({
                    "job_id":      f"naukri_govt_{uid}",
                    "source":      "naukri_govt",
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
            time.sleep(0.8)
        except Exception as e:
            logger.warning("[Naukri Govt] Error for '%s': %s", term, e)

    logger.info("[Naukri Govt] %d listings", len(jobs))
    return jobs


# ── 3. LinkedIn — government jobs India ──────────────────────────────────────
def _scrape_linkedin_govt(session) -> list[dict]:
    jobs = []
    seen = set()

    searches = [
        {"keywords": "government internship data science", "location": "India"},
        {"keywords": "PSU internship python", "location": "India"},
        {"keywords": "NITI Aayog intern", "location": "India"},
        {"keywords": "government research analyst fresher", "location": "India"},
        {"keywords": "public sector data analyst", "location": "India"},
        {"keywords": "DRDO ISRO internship", "location": "India"},
    ]

    for search in searches:
        for start in [0, 25]:
            params = {
                "keywords": search["keywords"],
                "location": search["location"],
                "f_JT":     "I",
                "start":    start,
            }
            resp = _safe_get(session, "https://www.linkedin.com/jobs/search", params=params)
            if not resp:
                break

            soup  = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".job-search-card") or soup.select("[data-entity-urn]")
            if not cards:
                break

            for card in cards:
                try:
                    title_el   = card.select_one("h3.base-search-card__title")
                    company_el = card.select_one("h4.base-search-card__subtitle a") or card.select_one("h4.base-search-card__subtitle")
                    loc_el     = card.select_one(".job-search-card__location")
                    link_el    = card.select_one("a.base-card__full-link") or card.select_one("a[href*='linkedin.com/jobs']")

                    if not title_el or not link_el:
                        continue

                    url = link_el["href"].split("?")[0]
                    jid = _job_id("linkedin_govt", url)
                    if jid in seen:
                        continue
                    seen.add(jid)

                    jobs.append({
                        "job_id":      jid,
                        "source":      "linkedin_govt",
                        "title":       title_el.get_text(strip=True),
                        "company":     company_el.get_text(strip=True) if company_el else "Government",
                        "location":    loc_el.get_text(strip=True) if loc_el else "India",
                        "duration":    None,
                        "stipend":     None,
                        "url":         url,
                        "tags":        ["government", "india", search["keywords"].split()[0].lower()],
                        "description": f"{title_el.get_text(strip=True)} government role. {search['keywords']}.",
                        "scraped_at":  datetime.now().isoformat(),
                    })
                except Exception as e:
                    logger.debug("LinkedIn govt card error: %s", e)
            time.sleep(DELAY)

    logger.info("[LinkedIn Govt] %d listings", len(jobs))
    return jobs


# ── 4. Unstop — govt challenges / PSU competitions ───────────────────────────
def _scrape_unstop_govt(session) -> list[dict]:
    jobs = []
    seen = set()

    search_terms = [
        "government", "PSU", "UPSC", "civil services",
        "policy", "public sector", "DRDO", "ISRO", "NITI",
    ]

    for term in search_terms:
        try:
            params = {
                "opportunity": "internship,hackathon,competition,job",
                "search":      term,
                "page":        1,
                "per_page":    20,
            }
            resp = requests.get(
                "https://unstop.com/api/public/opportunity/search-result",
                params=params,
                headers=HEADERS,
                timeout=12
            )
            if resp.status_code != 200:
                continue
            data  = resp.json()
            items = data.get("data", {}).get("data", []) or []

            for item in items:
                title   = item.get("title") or item.get("name", "")
                company = item.get("organisation", {}).get("name", "Government")
                url     = f"https://unstop.com/{item.get('public_url', '')}"
                jid     = _job_id("unstop_govt", url)
                if jid in seen:
                    continue
                seen.add(jid)

                prize   = item.get("prize_money") or item.get("stipend_range")
                tags    = [t.get("name", "").lower() for t in item.get("skills", [])]
                tags   += ["government", "india"]

                jobs.append({
                    "job_id":      jid,
                    "source":      "unstop_govt",
                    "title":       title,
                    "company":     company,
                    "location":    item.get("eligible_regions", "India"),
                    "duration":    item.get("duration"),
                    "stipend":     str(prize) if prize else None,
                    "url":         url,
                    "tags":        tags,
                    "description": item.get("short_description", "")[:500],
                    "scraped_at":  datetime.now().isoformat(),
                })
            time.sleep(0.8)
        except Exception as e:
            logger.warning("[Unstop Govt] Error for '%s': %s", term, e)

    logger.info("[Unstop Govt] %d listings", len(jobs))
    return jobs


# ── 5. Static high-value govt portals ────────────────────────────────────────
def _static_govt_portals() -> list[dict]:
    now = datetime.now().isoformat()
    return [
        {
            "job_id": "static_pm_internship",
            "source": "govt_portal",
            "title": "PM Internship Scheme — Top 500 Companies",
            "company": "Government of India (Ministry of Corporate Affairs)",
            "location": "Pan India",
            "duration": "12 months",
            "stipend": "₹5,000/month + ₹6,000 one-time grant",
            "url": "https://pminternship.mca.gov.in",
            "tags": ["government", "pm internship", "stipend", "india", "fresher"],
            "description": "1 crore internships in top 500 companies. ₹5000/month stipend + ₹6000 grant. Open for 21-24 year olds. Apply at pminternship.mca.gov.in.",
            "scraped_at": now,
        },
        {
            "job_id": "static_aicte",
            "source": "govt_portal",
            "title": "AICTE Internship Portal — Technical Roles",
            "company": "AICTE (All India Council for Technical Education)",
            "location": "Pan India",
            "duration": "2–6 months",
            "stipend": "₹10,000–₹25,000/month",
            "url": "https://internship.aicte-india.org",
            "tags": ["government", "aicte", "engineering", "technical", "internship"],
            "description": "AICTE internship portal for engineering students. Technical roles across PSUs and government bodies. B.Tech students eligible.",
            "scraped_at": now,
        },
        {
            "job_id": "static_isro",
            "source": "govt_portal",
            "title": "ISRO Student Internship Programme (RESPOND)",
            "company": "ISRO (Indian Space Research Organisation)",
            "location": "Bengaluru / Thiruvananthapuram / Ahmedabad",
            "duration": "2 months",
            "stipend": "₹10,000/month",
            "url": "https://www.isro.gov.in/Internship.html",
            "tags": ["government", "isro", "space", "research", "python", "engineering", "internship"],
            "description": "ISRO internship for B.Tech/M.Tech students in CS, Electronics. Work on real space missions and satellite systems.",
            "scraped_at": now,
        },
        {
            "job_id": "static_drdo",
            "source": "govt_portal",
            "title": "DRDO Research Internship for Students",
            "company": "DRDO (Defence Research and Development Organisation)",
            "location": "Pan India (Multiple Labs)",
            "duration": "1–6 months",
            "stipend": "₹5,000–₹15,000/month",
            "url": "https://www.drdo.gov.in/students-corner",
            "tags": ["government", "drdo", "defence", "research", "ai", "machine learning", "internship"],
            "description": "DRDO research internships in CS, AI, ML, Electronics. Work at defence labs. Apply via individual lab websites.",
            "scraped_at": now,
        },
        {
            "job_id": "static_niti_aayog",
            "source": "govt_portal",
            "title": "NITI Aayog Young Professional / Internship Programme",
            "company": "NITI Aayog (Government of India)",
            "location": "New Delhi",
            "duration": "3–6 months",
            "stipend": "₹10,000–₹25,000/month",
            "url": "https://www.niti.gov.in/internship",
            "tags": ["government", "niti aayog", "policy", "data", "research", "economics", "internship", "delhi"],
            "description": "Work with India's top policy think tank. Roles in data analytics, economic research, public policy. B.Tech/MBA/Economics students eligible.",
            "scraped_at": now,
        },
        {
            "job_id": "static_rbi",
            "source": "govt_portal",
            "title": "RBI Young Scholars / Internship Programme",
            "company": "Reserve Bank of India",
            "location": "Mumbai / Regional Offices",
            "duration": "3–6 months",
            "stipend": "₹15,000–₹35,000/month",
            "url": "https://www.rbi.org.in/Scripts/Opportunities.aspx",
            "tags": ["government", "rbi", "banking", "finance", "economics", "data", "internship"],
            "description": "RBI internship and young scholars programme. Roles in economics research, data analytics, monetary policy.",
            "scraped_at": now,
        },
        {
            "job_id": "static_sebi",
            "source": "govt_portal",
            "title": "SEBI Internship Programme",
            "company": "SEBI (Securities and Exchange Board of India)",
            "location": "Mumbai",
            "duration": "2 months",
            "stipend": "₹15,000/month",
            "url": "https://www.sebi.gov.in/careers.html",
            "tags": ["government", "sebi", "finance", "securities", "data analytics", "internship", "mumbai"],
            "description": "SEBI internship for finance, law, data analytics students. Work on securities market regulation and data analysis.",
            "scraped_at": now,
        },
        {
            "job_id": "static_nabard",
            "source": "govt_portal",
            "title": "NABARD Internship Programme",
            "company": "NABARD (National Bank for Agriculture and Rural Development)",
            "location": "Mumbai / Regional Offices",
            "duration": "2 months",
            "stipend": "₹10,000/month",
            "url": "https://www.nabard.org/content.aspx?id=572",
            "tags": ["government", "nabard", "finance", "rural", "economics", "internship"],
            "description": "NABARD internship for finance, economics, data students. Rural development and agricultural finance projects.",
            "scraped_at": now,
        },
        {
            "job_id": "static_mygov",
            "source": "govt_portal",
            "title": "MyGov Internship Opportunities Portal",
            "company": "Government of India (MyGov)",
            "location": "Pan India / Remote",
            "duration": "1–6 months",
            "stipend": "As per scheme",
            "url": "https://www.mygov.in/task-type/internship/",
            "tags": ["government", "mygov", "india", "policy", "social", "internship"],
            "description": "MyGov portal lists various government internship opportunities across ministries. Digital India, policy, social sector roles.",
            "scraped_at": now,
        },
        {
            "job_id": "static_csir",
            "source": "govt_portal",
            "title": "CSIR Research Internship / Junior Research Fellowship",
            "company": "CSIR (Council of Scientific & Industrial Research)",
            "location": "Pan India (38 Labs)",
            "duration": "2–6 months",
            "stipend": "₹12,000–₹31,000/month",
            "url": "https://www.csir.res.in/opportunities",
            "tags": ["government", "csir", "research", "science", "data", "python", "internship", "fellowship"],
            "description": "CSIR research internships across 38 national labs. Data science, AI, biotech, chemical, mechanical research roles.",
            "scraped_at": now,
        },
        {
            "job_id": "static_icar",
            "source": "govt_portal",
            "title": "ICAR Student Research Internship",
            "company": "ICAR (Indian Council of Agricultural Research)",
            "location": "Pan India",
            "duration": "1–3 months",
            "stipend": "₹5,000–₹10,000/month",
            "url": "https://icar.org.in/content/human-resource-development",
            "tags": ["government", "icar", "agriculture", "research", "data", "internship"],
            "description": "ICAR research internships in agricultural science, data analysis, agri-tech. Good for ML/data students interested in agri sector.",
            "scraped_at": now,
        },
        {
            "job_id": "static_nielit",
            "source": "govt_portal",
            "title": "NIELIT Internship / Project Trainee",
            "company": "NIELIT (National Institute of Electronics & IT)",
            "location": "Pan India (Multiple Centers)",
            "duration": "2–6 months",
            "stipend": "₹5,000–₹15,000/month",
            "url": "https://nielit.gov.in/content/career-opportunities",
            "tags": ["government", "nielit", "IT", "electronics", "python", "data", "internship"],
            "description": "NIELIT internships for CS/IT/Electronics students. Python, AI, cybersecurity, embedded systems roles.",
            "scraped_at": now,
        },
        {
            "job_id": "static_nic",
            "source": "govt_portal",
            "title": "NIC (National Informatics Centre) Internship",
            "company": "NIC — Ministry of Electronics & IT",
            "location": "New Delhi / State Centers",
            "duration": "2–4 months",
            "stipend": "₹10,000–₹15,000/month",
            "url": "https://www.nic.in/careers/",
            "tags": ["government", "nic", "IT", "python", "data", "software", "internship", "delhi"],
            "description": "NIC internships for CS/IT students. Work on e-governance projects, data platforms, national digital infrastructure.",
            "scraped_at": now,
        },
        {
            "job_id": "static_meity",
            "source": "govt_portal",
            "title": "MeitY Internship — Digital India Projects",
            "company": "MeitY (Ministry of Electronics & Information Technology)",
            "location": "New Delhi",
            "duration": "2–6 months",
            "stipend": "₹10,000–₹20,000/month",
            "url": "https://www.meity.gov.in/content/internship",
            "tags": ["government", "meity", "digital india", "IT", "policy", "data", "internship"],
            "description": "MeitY internships on Digital India, AI policy, cybersecurity, e-governance. B.Tech CS/IT students preferred.",
            "scraped_at": now,
        },
        {
            "job_id": "static_iit_research",
            "source": "govt_portal",
            "title": "IIT Research Internship (SRFP / SURGE / SPARK)",
            "company": "IITs (via DST-SERB / Individual Programs)",
            "location": "Pan India (IIT Campuses)",
            "duration": "2 months (Summer)",
            "stipend": "₹10,000–₹20,000/month",
            "url": "https://www.iitb.ac.in/en/education/surge-program",
            "tags": ["research", "iit", "data science", "machine learning", "python", "internship", "academic"],
            "description": "IIT research internships (SURGE/SPARK/SRFP) for B.Tech students. ML, data science, AI, systems research. Highly competitive but excellent for resume.",
            "scraped_at": now,
        },
        {
            "job_id": "static_dst_inspire",
            "source": "govt_portal",
            "title": "DST-INSPIRE Internship / Summer Research Fellowship",
            "company": "DST (Department of Science & Technology)",
            "location": "Pan India",
            "duration": "2 months",
            "stipend": "₹12,400/month + travel",
            "url": "https://online-inspire.gov.in",
            "tags": ["government", "dst", "research", "science", "data", "fellowship", "internship"],
            "description": "DST INSPIRE fellowship for science/engineering students. Research at top Indian institutions. Covers stipend + travel.",
            "scraped_at": now,
        },
    ]


# ── Main entry point ──────────────────────────────────────────────────────────
def scrape_govt_jobs() -> list[dict]:
    session = _session()
    all_jobs = {}

    def _merge(jobs: list[dict]):
        for j in jobs:
            all_jobs.setdefault(j["job_id"], j)

    print("  [1/5] Scraping Internshala govt/research/PSU/policy categories...")
    _merge(_scrape_internshala_govt(session))
    print(f"        → {len(all_jobs)} total so far")

    print("  [2/5] Scraping Naukri government jobs...")
    _merge(_scrape_naukri_govt(session))
    print(f"        → {len(all_jobs)} total so far")

    print("  [3/5] Scraping LinkedIn government jobs India...")
    _merge(_scrape_linkedin_govt(session))
    print(f"        → {len(all_jobs)} total so far")

    print("  [4/5] Scraping Unstop govt challenges & PSU competitions...")
    _merge(_scrape_unstop_govt(session))
    print(f"        → {len(all_jobs)} total so far")

    print("  [5/5] Adding high-value static govt portals (AICTE, ISRO, DRDO, NITI, PM, RBI, SEBI, CSIR, NIC, MeitY, IIT, DST)...")
    _merge(_static_govt_portals())
    print(f"        → {len(all_jobs)} total so far")

    result = list(all_jobs.values())
    print(f"\n  ✅ Govt scraper total: {len(result)} unique listings")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    jobs = scrape_govt_jobs()
    print(f"\nTotal: {len(jobs)}")
    print("\nSample by source:")
    from collections import Counter
    for src, count in Counter(j["source"] for j in jobs).items():
        print(f"  {src:<25} {count}")
    print("\nTop 5 jobs:")
    for j in jobs[:5]:
        print(f"  [{j['source']}] {j['title']} — {j['company']}")
