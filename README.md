# 🔍 Searchy — AI Job Hunting Assistant

> Personal AI job hunting assistant for B.Tech CS students.
> Upload your resume once. Get matched internship alerts 24/7.

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
cd searchy
pip install -r requirements.txt
```

### 2. Configure credentials
```bash
# Edit searchy.env with your Telegram bot token + Gmail app password
nano searchy.env
```

### 3. Parse your resume
```bash
python utils/resume_parser.py path/to/your_resume.pdf
# → Creates profile.json automatically
```

### 4. Run the pipeline once (test)
```bash
python main.py
```

### 5. Launch the dashboard
```bash
streamlit run app.py
```

### 6. Start the scheduler (runs 4× daily)
```bash
python scheduler.py
```

---

## 📁 Project Structure

```
searchy/
├── utils/
│   ├── resume_parser.py    # PDF → profile.json
│   ├── matcher.py          # AI match scoring (TF-IDF + cosine)
│   └── filters.py          # Job filtering rules
├── scrapers/
│   ├── internshala_scraper.py  # Internshala listings
│   └── company_scraper.py      # LinkedIn, Unstop, Wellfound
├── database/
│   └── db.py               # SQLite3 data layer
├── notifiers/
│   ├── telegram_notifier.py  # Real-time Telegram alerts
│   └── email_notifier.py     # Beautiful HTML digest emails
├── main.py                 # Orchestrates the full pipeline
├── scheduler.py            # Runs pipeline on schedule
├── app.py                  # Streamlit dashboard UI
├── requirements.txt
└── searchy.env             # Your credentials (keep private!)
```

---

## ⚙️ Pipeline Flow

```
resume.pdf
    │
    ▼
resume_parser.py → profile.json
    │
    ▼
scrapers/ → raw job listings
    │
    ▼
filters.py → filter out irrelevant jobs
    │
    ▼
matcher.py → AI match score (0–100)
    │
    ▼
db.py → store in SQLite
    │
    ├──→ telegram_notifier.py → real-time alerts (score ≥ 55)
    └──→ email_notifier.py   → daily digest    (score ≥ 35)
```

---

## 📱 Telegram Setup
1. Message `@BotFather` → `/newbot` → copy token
2. Message `@userinfobot` → copy your chat ID
3. Paste both into `searchy.env`

## 📧 Gmail Setup
1. Enable 2FA on Gmail
2. Go to **Google Account → Security → App Passwords**
3. Generate app password for "Mail"
4. Paste into `searchy.env` as `EMAIL_PASSWORD`

---

## 🏃 CLI Reference

```bash
# Parse new resume
python main.py --parse-resume resume.pdf

# Run pipeline, no notifications
python main.py --no-telegram --no-email

# Send digest only
python main.py --digest-only

# Scheduler: one-shot (for cron)
python scheduler.py --once

# Scheduler: continuous
python scheduler.py
```

---

## 🔧 Customise Filters
Edit `utils/filters.py → DEFAULT_PREFERENCES`:
- `min_match_score` — minimum AI score (default 40)
- `min_stipend` — minimum monthly stipend in INR
- `job_types` — internship / fresher / freelance / hackathon
- `required_skills` — must-have skills
- `exclude_keywords` — hard-block titles

---

## 📦 Tech Stack (all free)
| Component | Library |
|-----------|---------|
| Scraping | requests + BeautifulSoup |
| PDF | pdfplumber |
| AI Score | scikit-learn TF-IDF |
| Database | SQLite3 |
| Telegram | python-telegram-bot |
| Email | smtplib (built-in) |
| Scheduler | schedule |
| Dashboard | Streamlit + Plotly |

---

Built with ❤️ for B.Tech CS students who'd rather build projects than scroll job boards.
