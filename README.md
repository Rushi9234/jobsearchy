# 🔍 JobSearcher — AI Job Hunting Agent

> **Every other platform is a job board. JobSearcher is a job hunting agent.**
> Upload your resume once → scrapes 500+ jobs from 7 platforms → scores every job against your resume using AI → sends alerts automatically. You do zero work after signup.

**🌐 Live at: [jobsearchy.onrender.com](https://jobsearchy.onrender.com)**

---

## 🎯 What It Does

| Step | What happens |
|------|-------------|
| 1 | Upload your resume (PDF / DOCX) |
| 2 | System auto-extracts your name, skills, education, projects |
| 3 | 7 scrapers run in parallel — Internshala, LinkedIn, Unstop, Devfolio, HackerEarth, Govt portals |
| 4 | Every job is scored 0–100 against your resume using TF-IDF cosine similarity |
| 5 | Results appear on your dashboard ranked by match score |
| 6 | Pipeline repeats automatically 4× daily — 8AM, 12PM, 6PM, 11PM |
| 7 | Top matches sent to your email and Telegram |

---

## 🚀 Features

- **AI Resume Matching** — TF-IDF + cosine similarity scores every job against your actual skills
- **7 Live Scrapers** — Internshala, LinkedIn, Unstop, Devfolio, HackerEarth, Govt portals running in parallel
- **React Dashboard** — 8 tabs: All Jobs, Top Matches, Saved, Analytics, My Applications, Hackathons, Skill Gaps, Resume
- **Arc Gauge Score Rings** — visual 0–100 match score on every job card
- **Application Tracker** — track Applied / Interview / Offer / Rejected, saved to DB
- **Skill Gap Analysis** — domain-aware gaps (AI/ML, Web Dev, DevOps, Research) with YouTube learn links
- **AI Skill Flashcards** — 35 cards with full learning content, generated during pipeline run
- **Email Digest** — personalised HTML email with top job matches, Gmail SSL port 465
- **Telegram Alerts** — real-time bot notifications for high-match jobs
- **WhatsApp Share** — one-tap share of top 5 jobs via wa.me deep link
- **Auto Scheduler** — runs 4× daily without any manual intervention
- **GitHub CI/CD** — push to main → auto-deploys to Render

---

## 🗂️ Project Structure

```
jobsearchy/
│
├── web_portal.py           ← Flask backend — 15+ API endpoints (MAIN FILE)
├── main.py                 ← Standalone pipeline runner
├── scheduler.py            ← 4× daily auto-runner (08:00, 12:00, 18:00, 23:00)
├── requirements.txt
├── Procfile                ← Render deployment config
├── searcy.env.example      ← Credential template (safe to share)
│
├── static/
│   └── index.html          ← Full React frontend (React 18 + Babel CDN)
│
├── database/
│   └── db.py               ← SQLite layer — jobs, tracker, scrape logs
│
├── utils/
│   ├── resume_parser.py    ← PDF/DOCX → profile.json (name, skills, education, projects)
│   ├── matcher.py          ← TF-IDF + cosine scoring engine (0–100)
│   └── filters.py          ← Job filtering — removes spam, keeps internships/hackathons
│
├── scrapers/
│   ├── internshala_scraper.py   ← ~345 listings/run
│   ├── company_scraper.py       ← LinkedIn ~244 listings/run
│   ├── unstop_scraper.py        ← Hackathons
│   ├── devfolio_scraper.py      ← Hackathons
│   ├── hackerearth_scraper.py   ← Coding challenges
│   ├── wellfound_scraper.py     ← Startup jobs
│   └── naukri_scraper.py        ← Fresher jobs
│
└── notifiers/
    ├── telegram_notifier.py     ← Real-time alerts
    └── email_notifier.py        ← HTML digest — Gmail SSL port 465
```

---

## ⚙️ How the Pipeline Works

```
resume.pdf / .docx
       │
       ▼
resume_parser.py  →  profile.json  (name, skills dict, education, projects, domain)
       │
       ▼
7 scrapers run in parallel (ThreadPoolExecutor)
       │
       ▼
filters.py  →  remove spam, keep internships / hackathons / fresher roles
       │
       ▼
matcher.py  →  TF-IDF cosine similarity  →  match_score 0–100 per job
       │
       ▼
db.py  →  insert new jobs into SQLite, skip duplicates
       │
       ├──→  telegram_notifier.py  →  alert for score ≥ 30
       └──→  email_notifier.py    →  digest for score ≥ 20
```

### Scoring Formula
```
W_COSINE    = 0.35   # TF-IDF semantic similarity
W_SKILL     = 0.40   # skill overlap: matched / sqrt(min(profile_skills, job_skills×2))
W_EDUCATION = 0.15   # degree match
W_YEAR      = 0.10   # year of study fit

Final Score = (W_COSINE×cosine + W_SKILL×skill + W_EDU×edu + W_YEAR×yr) × 100
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.14 |
| Backend | Flask |
| Frontend | React 18 + Babel CDN (no npm, no build step) |
| AI Scoring | scikit-learn — TF-IDF + cosine similarity |
| Scraping | BeautifulSoup + requests |
| Resume Parsing | pdfplumber |
| Database | SQLite3 |
| Notifications | python-telegram-bot + Gmail SMTP (SSL port 465) |
| Scheduler | schedule library |
| Charts | Plotly |
| Deployment | Render.com (free tier) |
| CI/CD | GitHub → Render auto-deploy |

---

## 🔧 Local Setup

### 1. Clone & install

```bash
git clone https://github.com/Rushi9234/jobsearchy.git
cd jobsearchy
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp searcy.env.example searchy.env
# Edit searchy.env and fill in your values
```

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
MAIL_FROM=your_email@gmail.com
MAIL_PASS=your_gmail_app_password
MAIL_TO=recipient@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
```

### 3. Run locally

```bash
python web_portal.py
# Open http://localhost:5000
```

### 4. Upload your resume on the dashboard → click Find My Jobs

---

## 📱 Telegram Setup

1. Message `@BotFather` on Telegram → `/newbot` → copy the token
2. Message `@userinfobot` → copy your chat ID
3. Paste both into `searchy.env`

## 📧 Gmail Setup

1. Enable 2FA on your Gmail account
2. Go to **Google Account → Security → App Passwords**
3. Generate an app password for "Mail"
4. Paste into `searchy.env` as `MAIL_PASS`

---

## 🌐 Deployment (Render.com)

This project is deployed on [Render.com](https://render.com) free tier.

**To deploy your own instance:**

1. Fork this repo
2. Connect to Render → New Web Service → select your fork
3. Set environment variables (same as `searchy.env`) in Render dashboard
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn web_portal:app`
6. Deploy — every push to `main` auto-deploys

---

## 📊 Current Stats

| Metric | Value |
|--------|-------|
| Jobs scraped per run | 500+ |
| Active scrapers | 7 |
| Jobs in DB | 1483+ |
| Top match score | 64.2% |
| Auto-scan schedule | 4× daily |
| Email delivery | Gmail SSL, 500/day free |
| Deployment | Live on Render |

---

## 🗺️ Roadmap

- [ ] Fix hackathons tab (job_type not persisting to DB)
- [ ] Interview prep per job — AI-generated questions from JD
- [ ] Resume strength card — "You are strong in: Python, XGBoost"
- [ ] Deadline countdown on hackathon cards
- [ ] Dark mode toggle
- [ ] Skeleton loading states
- [ ] Confetti animation on 80+ score match
- [ ] ATS score checker — paste JD, see if resume passes
- [ ] Weekly auto email digest — every Monday 9AM
- [ ] Multi-user support with Supabase

---

## 🚫 Never Push to GitHub

```
searchy.env
profile.json
searchy.db
searchy.log
*.pdf
__pycache__/
```

---

## 👤 Author

**Rushikesh Baban Kedar**
B.Tech Computer Science Engineering | MIT Academy of Engineering, Pune (2023–2027)
GitHub: [Rushi9234](https://github.com/Rushi9234)
LinkedIn: [rushikesh-kedar](https://linkedin.com/in/rushikesh-kedar-87106b373)
Email: rushikedar40@gmail.com

---

## 📄 License

For academic and portfolio purposes only.
