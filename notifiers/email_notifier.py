"""
email_notifier.py — JobSearchy Email Notifier
Sends a professional HTML digest email via Gmail SMTP.
Completely free — only needs a Gmail app password.
"""

import smtplib
import logging
import os
import json
import html
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

PLATFORM_NAME = "JobSearchy"
PLATFORM_TAGLINE = "AI-Powered Job Discovery for Students"


def _get_config() -> dict:
    # Load searchy.env file if it exists (local development)
    env_path = os.path.join(os.path.dirname(__file__), "..", "searchy.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    cfg = {
        "resend_api_key":  os.getenv("RESEND_API_KEY", "").strip(),
        "sender_email":    os.getenv("MAIL_FROM") or os.getenv("EMAIL_SENDER"),
        "sender_password": os.getenv("MAIL_PASS") or os.getenv("EMAIL_PASSWORD"),
        "recipient_email": os.getenv("MAIL_TO") or os.getenv("EMAIL_RECIPIENT"),
        "smtp_host":       os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port":       int(os.getenv("SMTP_PORT", "465")),
    }

    return cfg


def _score_color(score: float) -> str:
    if score >= 70: return "#16a34a"
    if score >= 50: return "#d97706"
    return "#6b7280"

def _score_label(score: float) -> str:
    if score >= 80: return "Excellent Match"
    if score >= 60: return "Good Match"
    if score >= 40: return "Decent Match"
    return "Possible Match"

def _get_tags(job: dict) -> list:
    tags = job.get("tags", [])
    if isinstance(tags, str):
        try: tags = json.loads(tags)
        except: tags = []
    return [str(t) for t in tags[:5] if t]


def _job_card(job: dict) -> str:
    score    = job.get("match_score", 0)
    color    = _score_color(score)
    label    = _score_label(score)
    tags     = _get_tags(job)
    stipend  = html.escape(str(job.get("stipend") or "—"))
    duration = html.escape(str(job.get("duration") or "—"))
    location = html.escape(str(job.get("location") or "India"))
    title    = html.escape(str(job.get("title", "Opportunity")))
    company  = html.escape(str(job.get("company", "Company")))
    raw_url  = str(job.get("url", "#"))
    url      = html.escape(raw_url) if raw_url.startswith("http") else "#"

    tags_html = "".join(
        f'<span style="display:inline-block;background:#f0f9ff;color:#0369a1;'
        f'border:1px solid #bae6fd;border-radius:20px;padding:2px 10px;'
        f'font-size:11px;margin:2px 1px;font-weight:500;">{html.escape(t)}</span>'
        for t in tags
    )

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border:1px solid #e2e8f0;border-radius:12px;
                  margin-bottom:12px;overflow:hidden;background:#ffffff;">
      <tr>
        <td style="padding:16px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="vertical-align:top;width:52px;padding-right:14px;">
                <div style="width:46px;height:46px;border-radius:50%;
                            background:{color};color:white;text-align:center;
                            line-height:46px;font-weight:800;font-size:14px;
                            box-shadow:0 2px 8px {color}44;">
                  {int(score)}
                </div>
              </td>
              <td style="vertical-align:top;">
                <a href="{url}" style="font-size:15px;font-weight:700;
                   color:#1e293b;text-decoration:none;line-height:1.4;
                   display:block;margin-bottom:4px;">{title}</a>
                <div style="font-size:13px;color:#475569;margin-bottom:8px;">
                   <strong>{company}</strong>
                  &nbsp;&nbsp; {location}
                  &nbsp;&nbsp; {duration}
                  &nbsp;&nbsp; {stipend}
                </div>
                <div style="margin-bottom:10px;">{tags_html}</div>
                <table cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="padding-right:8px;">
                      <span style="display:inline-block;background:{color}18;
                             color:{color};border-radius:6px;padding:3px 10px;
                             font-size:12px;font-weight:600;">
                        {label} &nbsp;{int(score)}/100
                      </span>
                    </td>
                    <td>
                      <a href="{url}"
                         style="display:inline-block;background:#2563eb;
                                color:white;border-radius:6px;padding:4px 16px;
                                font-size:12px;font-weight:600;text-decoration:none;">
                        Apply Now &rarr;
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>"""


def _section(title: str, emoji: str, jobs: list, color: str) -> str:
    if not jobs:
        return ""
    cards = "".join(_job_card(j) for j in jobs[:5])
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
      <tr>
        <td style="padding-bottom:12px;border-bottom:2px solid {color}33;margin-bottom:14px;">
          <span style="font-size:16px;font-weight:800;color:#1e293b;">
            {emoji} {title}
          </span>
          <span style="float:right;font-size:12px;color:#94a3b8;
                       background:#f8fafc;border-radius:20px;
                       padding:2px 10px;border:1px solid #e2e8f0;">
            {len(jobs)} found
          </span>
        </td>
      </tr>
      <tr><td style="padding-top:12px;">{cards}</td></tr>
    </table>"""


def _detect_domain(all_skills: list) -> str:
    """Detect primary domain from skills."""
    skill_set = {s.lower() for s in all_skills}
    scores = {
        "aiml":        len(skill_set & {"machine learning","deep learning","tensorflow","pytorch","keras","xgboost","nlp","computer vision","huggingface","scikit-learn","sklearn","llm","langchain","transformers"}),
        "datascience": len(skill_set & {"pandas","numpy","matplotlib","seaborn","data analysis","data science","tableau","power bi","statistics","econometrics","statsmodels","plotly","scipy","r","excel"}),
        "webdev":      len(skill_set & {"react","angular","vue","node.js","nodejs","express","django","flask","fastapi","html","css","javascript","typescript","graphql","rest","api"}),
        "devops":      len(skill_set & {"docker","kubernetes","aws","gcp","azure","terraform","ansible","jenkins","linux","bash","github actions"}),
        "research":    len(skill_set & {"research","econometrics","statsmodels","ols","adf","scipy","survey design","literature review","data collection","r"}),
        "entc":        len(skill_set & {"arduino","raspberry pi","embedded","verilog","digital electronics","matlab","microcontroller","iot"}),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "datascience"


def _skill_gap_section(all_skills: list, jobs: list) -> str:
    """Compute domain-aware skill gaps based on user profile."""
    if not jobs:
        return ""
    import re

    domain = _detect_domain(all_skills)

    domain_skills = {
        "aiml":        ["mlflow","mlops","huggingface","langchain","llm","fastapi","docker","aws","pytorch","tensorflow","cuda","wandb","airflow","spark","kubernetes","redis","postgresql","git","linux"],
        "datascience": ["sql","postgresql","tableau","power bi","spark","hadoop","airflow","docker","aws","mongodb","redis","git","linux","dbt","bigquery","snowflake","kafka","looker"],
        "webdev":      ["typescript","docker","postgresql","mongodb","redis","aws","kubernetes","graphql","next.js","tailwind","prisma","jest","ci/cd","linux","nginx","elasticsearch"],
        "devops":      ["terraform","ansible","kubernetes","prometheus","grafana","vault","helm","argocd","datadog","python","bash","go","aws","gcp","azure"],
        "research":    ["stata","r","latex","spss","sql","tableau","power bi","python","pandas","scipy","statsmodels","excel","git","docker","postgresql"],
        "entc":        ["python","matlab","tensorflow","pytorch","opencv","mqtt","docker","postgresql","git","linux","node.js","flask","fastapi","aws iot"],
    }

    common_skills = domain_skills.get(domain, domain_skills["datascience"])
    job_text = " ".join(
        (j.get("title","") + " " + j.get("description","") + " " +
         " ".join(_get_tags(j))).lower()
        for j in jobs[:50]
    )
    profile_skill_set = {s.lower() for s in all_skills}
    gaps = []
    for skill in common_skills:
        if skill not in profile_skill_set:
            count = len(re.findall(r'\b' + re.escape(skill) + r'\b', job_text))
            if count >= 3:
                gaps.append((skill, count))
    gaps.sort(key=lambda x: -x[1])
    top_gaps = gaps[:6]
    if not top_gaps:
        return ""

    gap_pills = "".join(
        f'<span style="display:inline-block;background:#fef3c7;color:#92400e;'
        f'border:1px solid #fcd34d;border-radius:20px;padding:4px 14px;'
        f'font-size:13px;margin:3px;font-weight:600;">+ {g[0].title()}</span>'
        for g in top_gaps
    )
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#fffbeb;border:1px solid #fcd34d;
                  border-radius:12px;margin-bottom:28px;">
      <tr>
        <td style="padding:20px;">
          <div style="font-size:15px;font-weight:800;color:#92400e;margin-bottom:6px;">
            &#127919; Skill Gaps — Add These to Get More Matches
          </div>
          <div style="font-size:13px;color:#78350f;margin-bottom:14px;">
            These skills appear frequently in jobs but are missing from your resume:
          </div>
          <div>{gap_pills}</div>
        </td>
      </tr>
    </table>"""


def _build_html(
    jobs: list,
    user_name: str = "there",
    user_email: str = "",
    all_skills: list = None,
) -> str:
    now = datetime.now()
    date_str = now.strftime("%A, %d %B %Y")
    time_str = now.strftime("%I:%M %p")

    # Unified category classification
    try:
        from web_portal import classify_job
    except ImportError:
        def classify_job(j):
            return "job"

    internships = [j for j in jobs if classify_job(j) == "internship"]
    hackathons  = [j for j in jobs if classify_job(j) == "hackathon"]
    govt        = [j for j in jobs if classify_job(j) == "govt"]
    fulltime    = [j for j in jobs if classify_job(j) == "job"]

    # Top matches — best scoring from all
    top = sorted(jobs, key=lambda x: x.get("match_score",0), reverse=True)[:8]

    # Remaining after top shown
    shown_urls = {j.get("url") for j in top}
    remaining_internships = [j for j in internships if j.get("url") not in shown_urls]
    remaining_hackathons  = [j for j in hackathons  if j.get("url") not in shown_urls]
    remaining_govt        = [j for j in govt        if j.get("url") not in shown_urls]

    top_score    = max((j.get("match_score",0) for j in jobs), default=0)
    above_50     = sum(1 for j in jobs if j.get("match_score",0) >= 50)
    above_30     = sum(1 for j in jobs if j.get("match_score",0) >= 30)
    source_count = len(set(j.get("source","") for j in jobs))

    first_name = user_name.split()[0] if user_name and user_name != "there" else "there"

    top_section         = _section("Top Matches For You", "&#9733;", top, "#2563eb")
    internship_section  = _section("Internships", "&#128188;", remaining_internships, "#16a34a")
    hackathon_section   = _section("Hackathons & Competitions", "&#9889;", remaining_hackathons, "#7c3aed")
    govt_section        = _section("Government Opportunities", "&#127963;", remaining_govt, "#dc2626")
    gap_section         = _skill_gap_section(all_skills or [], jobs)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>JobSearchy — Your Results</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 0 40px;">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0"
       style="background:white;border-radius:20px;
              box-shadow:0 8px 40px rgba(0,0,0,0.10);overflow:hidden;
              max-width:620px;">

  <!-- â”€â”€ HEADER â”€â”€ -->
  <tr>
    <td style="background:linear-gradient(135deg,#1e3a8a 0%,#2563eb 60%,#3b82f6 100%);
               padding:36px 40px 28px;text-align:center;">
      <div style="font-size:32px;margin-bottom:6px;"></div>
      <div style="color:white;font-size:26px;font-weight:900;
                  letter-spacing:-0.5px;margin-bottom:4px;">
        JobSearchy
      </div>
      <div style="color:#bfdbfe;font-size:13px;margin-bottom:20px;">
        {PLATFORM_TAGLINE}
      </div>
      <div style="background:rgba(255,255,255,0.15);border-radius:10px;
                  padding:14px 20px;display:inline-block;text-align:left;width:100%;
                  box-sizing:border-box;">
        <div style="color:white;font-size:18px;font-weight:700;margin-bottom:2px;">
          Hey {first_name}! 
        </div>
        <div style="color:#dbeafe;font-size:14px;line-height:1.5;">
          We scanned <strong style="color:white;">{len(jobs)} opportunities</strong>
          across <strong style="color:white;">{source_count} platforms</strong>
          and matched them against your resume.
          Here are the best results — sorted by AI match score.
        </div>
      </div>
    </td>
  </tr>

  <!-- â”€â”€ STATS BAR â”€â”€ -->
  <tr>
    <td style="background:#eff6ff;padding:0;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:16px 20px;text-align:center;
                     border-right:1px solid #dbeafe;">
            <div style="font-size:22px;font-weight:900;color:#1d4ed8;">{len(jobs)}</div>
            <div style="font-size:11px;color:#64748b;font-weight:600;">TOTAL FOUND</div>
          </td>
          <td style="padding:16px 20px;text-align:center;
                     border-right:1px solid #dbeafe;">
            <div style="font-size:22px;font-weight:900;color:#16a34a;">{int(top_score)}</div>
            <div style="font-size:11px;color:#64748b;font-weight:600;">TOP SCORE</div>
          </td>
          <td style="padding:16px 20px;text-align:center;
                     border-right:1px solid #dbeafe;">
            <div style="font-size:22px;font-weight:900;color:#7c3aed;">{above_50}</div>
            <div style="font-size:11px;color:#64748b;font-weight:600;">ABOVE 50</div>
          </td>
          <td style="padding:16px 20px;text-align:center;">
            <div style="font-size:22px;font-weight:900;color:#dc2626;">{above_30}</div>
            <div style="font-size:11px;color:#64748b;font-weight:600;">ABOVE 30</div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- â”€â”€ BODY â”€â”€ -->
  <tr>
    <td style="padding:32px 36px;">

      {top_section}
      {internship_section}
      {hackathon_section}
      {govt_section}
      {gap_section}

      <!-- Tip box -->
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#f0fdf4;border:1px solid #bbf7d0;
                    border-radius:12px;margin-bottom:24px;">
        <tr>
          <td style="padding:18px 20px;">
            <div style="font-size:14px;font-weight:700;color:#15803d;margin-bottom:6px;">
               Pro Tip from JobSearchy
            </div>
            <div style="font-size:13px;color:#166534;line-height:1.6;">
              Jobs with a score above 50 are strong matches — apply to these first.
              Scores above 30 are worth reading. Update your resume with more project
              details to improve your scores on the next scan.
            </div>
          </td>
        </tr>
      </table>

    </td>
  </tr>

  <!-- â”€â”€ FOOTER â”€â”€ -->
  <tr>
    <td style="background:#f8fafc;padding:24px 36px;
               border-top:1px solid #e2e8f0;text-align:center;">
      <div style="font-size:16px;margin-bottom:8px;"></div>
      <div style="font-size:14px;font-weight:700;color:#1e293b;margin-bottom:4px;">
        JobSearchy
      </div>
      <div style="font-size:12px;color:#94a3b8;margin-bottom:12px;">
        {PLATFORM_TAGLINE}
      </div>
      <div style="font-size:11px;color:#cbd5e1;">
        Scanned on {date_str} at {time_str} &nbsp;Â·&nbsp;
        Built by Rushikesh Kedar, MITAOE Pune &nbsp;Â·&nbsp;
        <a href="https://github.com/Rushi9234"
           style="color:#94a3b8;text-decoration:none;">GitHub</a>
      </div>
    </td>
  </tr>

</table>
</td></tr>
</table>

</body>
</html>"""


def _build_plain(jobs: list, user_name: str = "there") -> str:
    first_name = user_name.split()[0] if user_name and user_name != "there" else "there"
    top = sorted(jobs, key=lambda x: x.get("match_score",0), reverse=True)[:15]
    lines = [
        f"JOBSEARCHY — Your Job Results",
        "=" * 50,
        f"Hey {first_name}!",
        f"We found {len(jobs)} opportunities matching your profile.",
        "",
        "TOP MATCHES",
        "-" * 30,
    ]
    for i, job in enumerate(top, 1):
        lines.append(
            f"{i}. [{int(job.get('match_score',0))}/100] {job.get('title','?')}\n"
            f"   {job.get('company','?')} | {job.get('location','?')}\n"
            f"   Stipend: {job.get('stipend','—')} | Duration: {job.get('duration','—')}\n"
            f"   {job.get('url','')}\n"
        )
    lines += [
        "—",
        "Powered by JobSearchy — AI Job Discovery",
        "Built by Rushikesh Kedar, MITAOE Pune",
    ]
    return "\n".join(lines)


def send_daily_digest(
    jobs: list,
    recipient_email: Optional[str] = None,
    user_name: str = "there",
    all_skills: list = None,
) -> bool:
    if not jobs:
        logger.info("[Email] No jobs to send.")
        return True

    cfg = _get_config()
    if recipient_email and recipient_email.strip():
        cfg["recipient_email"] = recipient_email.strip()

    if not all([cfg["sender_email"], cfg["sender_password"], cfg["recipient_email"]]):
        logger.error("[Email] Missing MAIL_FROM, MAIL_PASS or MAIL_TO in environment")
        return False

    first_name = user_name.split()[0] if user_name and user_name != "there" else "there"
    top_score  = max((j.get("match_score",0) for j in jobs), default=0)
    subject    = f"JobSearchy — Hey {first_name} — {len(jobs)} opportunities found! Top score: {int(top_score)}/100"

    # Strategy 1: Resend HTTP REST API (Port 443 — always open on Render and Cloud)
    if cfg.get("resend_api_key"):
        try:
            from_field = "JobSearchy <onboarding@resend.dev>"
            if cfg.get("sender_email") and "@" in cfg["sender_email"] and "<" in cfg["sender_email"]:
                from_field = cfg["sender_email"]

            payload = {
                "from": from_field,
                "to": [cfg["recipient_email"]],
                "subject": subject,
                "html": _build_html(jobs, user_name, cfg["recipient_email"], all_skills or []),
                "text": _build_plain(jobs, user_name),
            }
            resp = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {cfg['resend_api_key']}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                logger.info("[Email via Resend HTTPS] Successfully sent to %s (%d jobs)", cfg["recipient_email"], len(jobs))
                return True
            else:
                logger.error("[Email via Resend] API returned HTTP %d: %s", resp.status_code, resp.text)
        except Exception as e:
            logger.error("[Email via Resend] Request error: %s", e)

    # Strategy 2: Direct SMTP (Timeout=8 prevents Render socket hangs)
    if not all([cfg.get("sender_email"), cfg.get("sender_password"), cfg.get("recipient_email")]):
        logger.error("[Email] Missing credentials. Set RESEND_API_KEY (recommended for Render) or MAIL_FROM/MAIL_PASS in environment.")
        return False

    try:
        import ssl
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"JobSearchy <{cfg['sender_email']}>"
        msg["To"]      = cfg["recipient_email"]
        msg.attach(MIMEText(_build_plain(jobs, user_name), "plain"))
        msg.attach(MIMEText(_build_html(jobs, user_name, cfg["recipient_email"], all_skills or []), "html"))

        context = ssl.create_default_context()
        if cfg["smtp_port"] == 587:
            with smtplib.SMTP(cfg["smtp_host"], 587, timeout=8) as server:
                server.starttls(context=context)
                server.login(cfg["sender_email"], cfg["sender_password"])
                server.sendmail(cfg["sender_email"], cfg["recipient_email"], msg.as_string())
        else:
            with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], context=context, timeout=8) as server:
                server.login(cfg["sender_email"], cfg["sender_password"])
                server.sendmail(cfg["sender_email"], cfg["recipient_email"], msg.as_string())

        logger.info("[Email via SMTP] Sent to %s (%d jobs)", cfg["recipient_email"], len(jobs))
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("[Email] Auth failed — check MAIL_FROM and MAIL_PASS (use Gmail App Password)")
        return False
    except (TimeoutError, smtplib.SMTPConnectError, OSError) as e:
        logger.error("[Email] Connection timed out / blocked: %s. On Render free tier, outbound SMTP ports 465/587 are blocked. Please set RESEND_API_KEY.", e)
        return False
    except Exception as e:
        logger.error("[Email] Error: %s", e)
        return False


def send_alert_email(job: dict) -> bool:
    return send_daily_digest([job])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_jobs = [
        {"title":"Data Science Intern","company":"Analytics Corp","location":"Remote",
         "duration":"3 months","stipend":"â‚¹15,000/month","url":"https://internshala.com",
         "tags":["python","data science","ml"],"match_score":72.5,"source":"internshala"},
        {"title":"ML Hackathon 2026","company":"Devfolio","location":"Online",
         "duration":"48 hours","stipend":"â‚¹50,000 prize","url":"https://devfolio.co",
         "tags":["machine learning","python"],"match_score":58.0,"source":"devfolio"},
        {"title":"NITI Aayog Internship","company":"NITI Aayog","location":"New Delhi",
         "duration":"3 months","stipend":"â‚¹15,000/month","url":"https://niti.gov.in",
         "tags":["research","data","policy"],"match_score":45.0,"source":"govt_portal"},
    ]
    ok = send_daily_digest(
        test_jobs,
        user_name="Rushikesh Baban Kedar",
        all_skills=["python","pandas","xgboost","scikit-learn","econometrics"]
    )
    print("âœ… Email sent!" if ok else "âŒ Failed — check searchy.env")

