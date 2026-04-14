# 🔍 JOBSEARCHER — COMPLETE PROJECT CONTEXT
*Paste this entire file at the start of every new Claude conversation*
*Last updated: 11-04-2026 — 03:30 AM*

---

## 👨‍💻 Developer
- **Name:** Rushikesh Baban Kedar
- **College:** MITAOE Pune, 3rd Year B.Tech CS (2023–2027)
- **Email:** rushikedar40@gmail.com
- **Telegram Chat ID:** 840683751

---

## 🎯 What JobSearcher Is
AI-powered job hunting agent for college students. Upload resume once → scrapes 7 portals → scores every job against resume using TF-IDF + cosine similarity (0-100) → shows ranked results on React dashboard → sends email/Telegram alerts automatically 4x daily.

**Tagline:** "Every other platform is a job board. JobSearcher is a job hunting agent. User does ZERO work after signup."

**Runs at:** `http://localhost:5000`

---

## 📁 Project Location
```
D:\searchy\
```

---

## 🗂️ Complete File Structure
```
D:\searchy\
│   web_portal.py           ← Flask backend (MAIN FILE)
│   app.py                  ← OLD Streamlit (ignore)
│   main.py                 ← Original standalone pipeline
│   scheduler.py            ← 4x daily (08:00,12:00,18:00,23:00)
│   requirements.txt
│   searchy.env             ← Credentials (NEVER SHARE)
│   searchy.env.example     ← Safe to share
│   profile.json            ← User resume data (NEVER SHARE)
│   searchy.db              ← SQLite database (NEVER SHARE)
│   searchy.log
│   README.md
│   JOBSEARCHER_CONTEXT.md  ← This file
│
├───static/
│   index.html              ← Complete React frontend
│
├───database/
│   db.py
│
├───utils/
│   resume_parser.py        ← PDF → profile.json
│   matcher.py              ← TF-IDF + cosine scoring
│   filters.py              ← Job filtering
│
├───scrapers/
│   internshala_scraper.py  ← scrape() — 338/run
│   company_scraper.py      ← scrape_linkedin()
│   unstop_scraper.py       ← scrape_unstop() — hackathons
│   devfolio_scraper.py     ← scrape_devfolio() — hackathons
│   hackerearth_scraper.py  ← scrape_hackerearth() — challenges
│   wellfound_scraper.py    ← scrape_wellfound() — startups
│   naukri_scraper.py       ← scrape_naukri() — fresher jobs
│
└───notifiers/
    telegram_notifier.py    ← send_daily_digest()
    email_notifier.py       ← send_daily_digest()
```

---

## 🚀 How to Run
```bash
cd D:\searchy
python web_portal.py
# Open http://localhost:5000
```

---

## ⚠️ CRITICAL FUNCTION SIGNATURES

```python
# Scrapers
from scrapers.internshala_scraper import scrape as scrape_internshala
from scrapers.company_scraper import scrape_linkedin
# Both: keywords=[] → list of job dicts
# Job dict keys: job_id, source, title, company, location,
#   duration, stipend, url, tags(list), description, scraped_at

# Database
from database.db import (
    init_db, get_all_jobs, get_top_jobs, get_saved_jobs,
    toggle_saved, get_stats, insert_job, is_seen, mark_seen
)
# is_seen(job_id, source)     ← BOTH args required
# mark_seen(job_id, source)   ← BOTH args required
# toggle_saved(job_id, bool)  ← bool second arg required
# insert_job needs: job_id, source, title, company, location,
#   duration, stipend, url, tags(list), description, match_score, scraped_at

# Matcher
from utils.matcher import batch_score
# batch_score(profile, jobs)  ← profile FIRST
# profile["skills"] MUST stay as DICT {technical:[...], soft:[...]}
# DO NOT flatten — matcher calls skills.get("technical") internally
# Returns: list of dicts with "match_score" key added

# Filters
from utils.filters import filter_jobs
# filter_jobs(jobs) → TUPLE (accepted, rejected)
# Usage: accepted, _ = filter_jobs(jobs)

# Email
from notifiers.email_notifier import send_daily_digest
# send_daily_digest(jobs) → bool
```

---

## 🗄️ Database
```sql
jobs: id, job_id, source, title, company, location, duration,
      stipend, url, tags(JSON string), description,
      match_score, scraped_at, is_saved, notified

IMPORTANT:
- DB stores "match_score" — frontend expects "score"
- web_portal.py normalizes: j["score"] = j["match_score"]
- tags = JSON string "[]" — parse with JSON.parse(job.tags||'[]')
```

---

## 🔧 searchy.env
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=840683751
EMAIL_SENDER=rushikedar40@gmail.com
EMAIL_PASSWORD=...
EMAIL_RECIPIENT=timepassnust@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

---

## 🌐 Frontend (static/index.html)

### Design System
```
Theme:    White/light, professional
Fonts:    Bricolage Grotesque (headings) + DM Sans (body)
Accent:   Indigo #4338ca
Stack:    React 18 + Babel CDN (no npm, no build step)
No emojis on buttons/UI — only 📍 location, ⏱ duration kept
```

### Pages
```
Hero landing    ← animated floating job cards, stats, CTA
Resume tab      ← drag-drop upload, skills display, Find My Jobs button
All Jobs tab    ← category filter tabs, search, scanning banner
Top Matches     ← sorted by score desc
Saved           ← bookmarked jobs
Analytics       ← score chart, source bars, company grid
```

### Job Card Design
```
- Position:relative card, overflow:hidden
- Absolute top colored bar (width = score%, animates on load)
- Row: [Company Avatar] [Title + Meta flex:1] [Arc Gauge]
- Company avatar: colored square, first letter of company name
- Arc gauge: SVG arc 78% sweep, thick stroke, glow effect
- Score color tiers:
    65+   → Dark green  #15803d  "Strong match"
    45-65 → Blue        #1d4ed8  "Good match"
    30-45 → Amber       #b45309  "Partial match"
    <30   → Red         #b91c1c  "Low match"
- Job type badge: Internship / Full-time / Hackathon / Govt
- Expandable description (2 lines → click ...more)
- Footer: source badge, skill tags, Apply + Save buttons
```

### Category Tab Detection (frontend, keyword-based)
```javascript
Hackathon  → /hackathon|ideathon|devfolio|unstop|dare2compete/
Govt       → /govt|niti aayog|isro|drdo|ministry|upsc|pradhan mantri/
Full-time  → /full-time|permanent/ AND no "intern" in title
Internship → /intern/ in title OR source==='internshala'
LinkedIn + no intern keyword → Full-time default
```

### Right Panel (job tabs only)
```
Find My Jobs button  ← visible only when profile loaded
Date Range slider    ← 1-30 days + quick chips
Run Pipeline button  ← rotating status messages while running
Email Digest input   ← send top jobs to email
Auto Schedule        ← 08:00/12:00/18:00/23:00 display
```

### Key UX
```
- Yellow banner while pipeline running (auto-disappears when done)
- Fun rotating messages during pipeline wait (no emojis)
- Email popup after pipeline finishes
- "Email me jobs" bar in All Jobs header
- Auto-refresh when pipeline completes
- No auto-loading last person's name on fresh open
- Profile only shown after fresh upload in session
```

### CSS Classes
```
.jc        → job card (block, no flex, position:relative)
.fu        → page wrapper
.ph/.pt/.ps → page header/title/subtitle
.uz        → upload zone
.pc        → profile card
.rp        → right panel
.fb        → filter bar
.src-badge → source badge
.sk-tag    → skill tag
.sk-pill   → skill pill
.inp       → input
.spinner   → loading spinner
.spinner-d → dark spinner
```

---

## 🔄 Pipeline Flow
```
1. Load profile.json → get skills dict
2. Top 5 skills as keywords
3. Scrape: Internshala → LinkedIn → Unstop → Devfolio
           → HackerEarth → Wellfound → Naukri
4. Filter by date (now - days cutoff)
5. filter_jobs(jobs) → (accepted, rejected)
6. batch_score(profile, accepted) → scored_jobs
7. Deduplicate by job_id (seen_this_run set)
8. Normalize: job["match_score"] → job["score"]
9. insert_job() + mark_seen() for new jobs
10. Dispatch pipeline-done event → frontend auto-refreshes
```

---

## 📊 Current Stats
```
Jobs in DB:      500+
Scrapers:        7 active
Scheduler:       4x daily
Telegram:        working
Email:           working
Match scores:    30-65 range (low due to known bug)
```

---

## 🐛 Known Bugs
```
1. LOW SCORES (30-45 range)
   Cause: skill_overlap = matched / sqrt(total_profile_skills)
   Too many profile skills → low denominator → low score
   Fix: change to matched / sqrt(job_required_skills)
   File: utils/matcher.py line ~68 _skill_overlap_score()
   Status: NOT FIXED

2. PROJECTS/CERTS = 0
   resume_parser.py not extracting projects from some PDF formats
   Status: NOT FIXED

3. NEW SCRAPERS may return 0
   Their APIs change. Fallback BS4 scrapers built in.
   Status: WORKING with fallbacks
```

---

## 🗺️ WHAT TO BUILD NEXT — IN ORDER

### 1. Resume Gap Analyzer (NEXT — most viral)
```
What: Compare user skills vs skills in top 50 DB jobs
Show: "Add Docker → found in 45 jobs (+40% matches)"
Where: Bottom of Resume tab
API: GET /api/skill-gaps
Logic:
  jobs = get_top_jobs(50)
  all_skills = extract from job descriptions
  missing = [s for s in all_skills if s not in user_skills]
  return ranked by frequency with score_boost estimate
```

### 2. Application Tracker
```
What: Kanban — Interested → Applied → Interview → Offer → Rejected
Where: New sidebar tab
DB: New table "applications"
Why: Daily use, keeps users coming back
```

### 3. Interview Prep per Job
```
What: Click job → AI generates 5 questions from JD
How: Claude API (available in artifacts)
Where: Button on job card → modal opens
Why: Huge value, nobody else does this free
```

### 4. Deadline Tracker
```
What: Parse closing dates from JD → countdown badges
Show: "Closes in 2 days" on card
Why: Easy, drives urgency
```

### 5. Skill Trends
```
What: Skills appearing most in this week's jobs
Where: Analytics tab new chart
Show: "Python: 340 jobs | React: 280 jobs"
```

### 6. More Scrapers
```
Dare2Compete, Freshersworld, LetsIntern,
MyGov (govt internships), Indeed India
```

### 7. Deploy Online
```
Backend: Render.com free tier
DB: SQLite → Supabase when multi-user
Steps: GitHub → Render → env vars → live
```

### 8. Multi-user
```
Auth + DB + Storage: Supabase free tier
Each user: own resume, matches, alerts
```

---

## 📝 Resume Entry
```
JobSearcher — AI Job Hunting Agent        Python, Flask, React, scikit-learn,
- Scrapes 500+ jobs/run from 7 portals   SQLite, BeautifulSoup, pdfplumber,
  including Internshala, LinkedIn,        Telegram Bot API, TF-IDF, HTML/CSS
  Unstop, Devfolio, Naukri automatically
- TF-IDF cosine scoring matches jobs
  to resume (0-100 score)
- React dashboard with hero page,
  arc gauge cards, analytics, email digest
- Pipeline 4x daily via scheduler
```

---

## 🚫 Never Push to GitHub
```
searchy.env, profile.json, searchy.db,
searchy.log, *.pdf, __pycache__/
```

## ✅ Safe to Push
```
web_portal.py, static/index.html,
database/db.py, utils/*.py, scrapers/*.py,
notifiers/*.py, scheduler.py, requirements.txt,
README.md, searchy.env.example,
JOBSEARCHER_CONTEXT.md
```

---

## 💬 How to Continue Tomorrow
```
"I'm building JobSearcher — AI job hunting agent.
Context file: [paste this]
Last built: [what you did]
Continue with: Resume Gap Analyzer"
```
