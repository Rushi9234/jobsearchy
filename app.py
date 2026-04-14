"""
app.py — Searchy Streamlit Dashboard
Beautiful, animated UI for browsing jobs, viewing match scores,
managing saved listings, and monitoring the pipeline.
Run: streamlit run app.py
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd

# ── Page config (must be FIRST Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Searchy — AI Job Hunter",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

from database.db import init_db, get_all_jobs, get_top_jobs, get_saved_jobs, \
    toggle_saved, get_stats, get_unnotified_jobs
from utils.resume_parser import load_profile, parse_resume, save_profile
from utils.matcher import explain_score

# ── Ensure DB exists ──────────────────────────────────────────────────────────
init_db()


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOM CSS + ANIMATIONS
# ═══════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* ── Fonts ──────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Root variables ─────────────────────── */
:root {
  --primary:    #3b82f6;
  --primary-d:  #1d4ed8;
  --success:    #22c55e;
  --warning:    #f59e0b;
  --danger:     #ef4444;
  --bg:         #0f172a;
  --surface:    #1e293b;
  --surface2:   #334155;
  --border:     #334155;
  --text:       #f1f5f9;
  --text-muted: #94a3b8;
  --radius:     14px;
}

/* ── Global ─────────────────────────────── */
* { font-family: 'Space Grotesk', sans-serif !important; box-sizing: border-box; }
.stApp { background: var(--bg); color: var(--text); }
.block-container { padding-top: 1.5rem !important; max-width: 1300px !important; }

/* ── Sidebar ────────────────────────────── */
[data-testid="stSidebar"] {
  background: var(--surface) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }

/* ── Animated header ────────────────────── */
@keyframes gradientShift {
  0%   { background-position: 0% 50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
.hero-header {
  background: linear-gradient(-45deg, #1e3a8a, #3b82f6, #0ea5e9, #6366f1);
  background-size: 400% 400%;
  animation: gradientShift 6s ease infinite;
  padding: 32px 40px;
  border-radius: 20px;
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
}
.hero-header::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 80% 50%, rgba(255,255,255,0.06) 0%, transparent 60%);
  pointer-events: none;
}
.hero-title {
  font-size: 2.2rem;
  font-weight: 800;
  color: white;
  margin: 0;
  letter-spacing: -1px;
  text-shadow: 0 2px 12px rgba(0,0,0,0.3);
}
.hero-sub {
  color: #bfdbfe;
  font-size: 1rem;
  margin-top: 6px;
  font-weight: 400;
}

/* ── Stat cards ─────────────────────────── */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(18px); }
  to   { opacity: 1; transform: translateY(0); }
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  animation: fadeUp 0.5s ease both;
  transition: transform 0.2s, box-shadow 0.2s;
}
.stat-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 28px rgba(0,0,0,0.25);
}
.stat-icon {
  font-size: 2rem;
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(59,130,246,0.15);
}
.stat-label { font-size: 12px; color: var(--text-muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
.stat-value { font-size: 1.9rem; font-weight: 700; color: var(--text); line-height: 1; }

/* ── Job card ───────────────────────────── */
@keyframes slideIn {
  from { opacity: 0; transform: translateX(-12px); }
  to   { opacity: 1; transform: translateX(0); }
}
.job-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  margin-bottom: 14px;
  animation: slideIn 0.35s ease both;
  transition: border-color 0.2s, transform 0.2s, box-shadow 0.2s;
  position: relative;
  overflow: hidden;
}
.job-card::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: var(--primary);
  border-radius: 4px 0 0 4px;
  opacity: 0;
  transition: opacity 0.2s;
}
.job-card:hover {
  border-color: var(--primary);
  transform: translateY(-2px);
  box-shadow: 0 6px 24px rgba(59,130,246,0.15);
}
.job-card:hover::before { opacity: 1; }

.job-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 4px;
  line-height: 1.3;
}
.job-meta {
  font-size: 0.82rem;
  color: var(--text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.job-meta span { display: flex; align-items: center; gap: 4px; }

/* Score badge */
.score-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 8px;
  padding: 4px 12px;
  font-size: 13px;
  font-weight: 700;
}
.score-high   { background: rgba(34,197,94,0.15);  color: #22c55e; }
.score-medium { background: rgba(245,158,11,0.15); color: #f59e0b; }
.score-low    { background: rgba(148,163,184,0.15); color: #94a3b8; }

/* Tags */
.tag {
  display: inline-block;
  background: rgba(59,130,246,0.15);
  color: #60a5fa;
  border-radius: 20px;
  padding: 2px 10px;
  font-size: 11.5px;
  font-weight: 500;
  margin: 2px;
}

/* Pill button */
.pill-btn {
  display: inline-block;
  background: var(--primary);
  color: white !important;
  border-radius: 8px;
  padding: 6px 16px;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none !important;
  transition: background 0.2s, transform 0.15s;
}
.pill-btn:hover { background: var(--primary-d); transform: scale(1.03); }

/* ── Progress bar override ──────────────── */
.stProgress > div > div { background: var(--primary) !important; }

/* ── Section headers ────────────────────── */
.section-header {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--text);
  padding-bottom: 8px;
  border-bottom: 2px solid var(--border);
  margin-bottom: 18px;
}

/* ── Spinner overlay ────────────────────── */
@keyframes spin { to { transform: rotate(360deg); } }
.spin { display: inline-block; animation: spin 1s linear infinite; }

/* ── Pulse dot ──────────────────────────── */
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.5; transform: scale(0.85); }
}
.pulse-dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--success);
  animation: pulse 1.5s ease-in-out infinite;
  margin-right: 6px;
}

/* ── Profile card ───────────────────────── */
.profile-card {
  background: linear-gradient(135deg, #1e3a8a22, #3b82f622);
  border: 1px solid rgba(59,130,246,0.3);
  border-radius: var(--radius);
  padding: 20px;
  text-align: center;
  margin-bottom: 20px;
}
.profile-name {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text);
  margin: 8px 0 2px;
}
.profile-detail { font-size: 0.8rem; color: var(--text-muted); }

/* ── Empty state ────────────────────────── */
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50%       { transform: translateY(-8px); }
}
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
  animation: fadeUp 0.6s ease;
}
.empty-icon {
  font-size: 3rem;
  animation: float 3s ease-in-out infinite;
  display: block;
  margin-bottom: 12px;
}

/* ── Tabs ───────────────────────────────── */
.stTabs [data-baseweb="tab-list"] { background: var(--surface) !important; border-radius: 12px; gap: 4px; padding: 4px; }
.stTabs [data-baseweb="tab"] { color: var(--text-muted) !important; border-radius: 8px !important; }
.stTabs [aria-selected="true"] { background: var(--primary) !important; color: white !important; }

/* ── Inputs ─────────────────────────────── */
.stTextInput input, .stSelectbox > div, .stMultiSelect > div {
  background: var(--surface2) !important;
  border-color: var(--border) !important;
  color: var(--text) !important;
  border-radius: 10px !important;
}
.stSlider [data-testid="stThumbValue"] { color: var(--primary) !important; }

/* ── Buttons ────────────────────────────── */
.stButton button {
  background: var(--primary) !important;
  color: white !important;
  border: none !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
  transition: all 0.2s !important;
}
.stButton button:hover {
  background: var(--primary-d) !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 14px rgba(59,130,246,0.35) !important;
}
.stButton.secondary button {
  background: var(--surface2) !important;
  color: var(--text) !important;
}

/* ── Metric override ────────────────────── */
[data-testid="metric-container"] {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 20px;
}
[data-testid="metric-container"] label { color: var(--text-muted) !important; }
[data-testid="metric-container"] [data-testid="metric-value"] { color: var(--text) !important; }

/* ── Score ring ─────────────────────────── */
@keyframes ringFill {
  from { stroke-dashoffset: 251; }
  to   { stroke-dashoffset: var(--offset); }
}
.score-ring svg { animation: ringFill 1.2s cubic-bezier(0.4,0,0.2,1) forwards; }

/* Hide Streamlit branding */
#MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════
def score_class(score: float) -> str:
    if score >= 70:
        return "score-high"
    if score >= 45:
        return "score-medium"
    return "score-low"


def score_emoji(score: float) -> str:
    if score >= 80: return "🔥"
    if score >= 65: return "⭐"
    if score >= 50: return "✅"
    return "💡"


def render_score_ring(score: float, size: int = 80) -> str:
    r = 38
    circ = 2 * 3.14159 * r
    offset = circ * (1 - score / 100)
    color = "#22c55e" if score >= 70 else ("#f59e0b" if score >= 45 else "#6b7280")
    return f"""
    <div class="score-ring" style="width:{size}px;height:{size}px;position:relative;">
      <svg width="{size}" height="{size}" viewBox="0 0 84 84">
        <circle cx="42" cy="42" r="{r}" fill="none" stroke="#334155" stroke-width="6"/>
        <circle cx="42" cy="42" r="{r}" fill="none" stroke="{color}" stroke-width="6"
                stroke-dasharray="{circ:.1f}"
                stroke-dashoffset="{offset:.1f}"
                stroke-linecap="round"
                transform="rotate(-90 42 42)"
                style="--offset:{offset:.1f};animation:ringFill 1.2s cubic-bezier(0.4,0,0.2,1) forwards;"/>
        <text x="42" y="47" text-anchor="middle" font-size="16" font-weight="700"
              fill="{color}" font-family="Space Grotesk, sans-serif">{score:.0f}</text>
      </svg>
    </div>"""


def render_job_card(job: dict, profile: dict = None, show_explain: bool = False, tab_name: str = "default"):
    tags     = job.get("tags") or []
    score    = job.get("match_score", 0) or 0
    saved    = job.get("is_saved", 0)
    tags_html = "".join(f'<span class="tag">{t}</span>' for t in tags[:7])
    sc        = score_class(score)
    em        = score_emoji(score)
    source_badge = f'<span style="font-size:11px;background:#1e40af33;color:#93c5fd;border-radius:6px;padding:2px 8px;">{job.get("source","?").upper()}</span>'

    st.markdown(f"""
    <div class="job-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;">
        <div style="flex:1;min-width:0;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;">
            {source_badge}
            <span class="score-badge {sc}">{em} {score:.0f}/100</span>
          </div>
          <p class="job-title">{job.get('title','N/A')}</p>
          <div class="job-meta">
            <span>🏢 <strong>{job.get('company','Unknown')}</strong></span>
            <span>📍 {job.get('location','?')}</span>
            <span>⏱ {job.get('duration') or 'N/A'}</span>
            <span>💰 {job.get('stipend') or 'Not specified'}</span>
          </div>
          <div style="margin-top:6px;">{tags_html}</div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:center;gap:10px;min-width:90px;">
          {render_score_ring(score, 72)}
          <a href="{job.get('url','#')}" target="_blank" class="pill-btn">View →</a>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Expandable AI explanation
    if show_explain and profile:
        with st.expander("🧠 Why this score?", expanded=False):
            try:
                detail = explain_score(profile, job)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("🔤 Semantic", f"{detail['cosine_score']:.0f}%")
                c2.metric("🎯 Skills",   f"{detail['skill_score']:.0f}%")
                c3.metric("🎓 Education",f"{detail['education_score']:.0f}%")
                c4.metric("📅 Year Fit", f"{detail['year_score']:.0f}%")

                if detail["matched_skills"]:
                    st.markdown("**✅ Matched skills:** " +
                                " ".join(f"`{s}`" for s in detail["matched_skills"][:10]))
                if detail["missing_skills"]:
                    st.markdown("**❌ Missing skills:** " +
                                " ".join(f"`{s}`" for s in detail["missing_skills"][:5]))
            except Exception:
                st.info("Score breakdown unavailable.")

    # Save / Unsave button
    col_a, col_b, _ = st.columns([1, 1, 6])
    with col_a:
        if saved:
            if st.button("❤️ Saved", key=f"unsave_{job['id']}_{tab_name}"):
                toggle_saved(job["id"], False)
                st.rerun()
        else:
            if st.button("🤍 Save", key=f"save_{job['id']}_{tab_name}"):
                toggle_saved(job["id"], True)
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style="text-align:center;padding:16px 0 8px;">
      <div style="font-size:2.2rem;">🔍</div>
      <div style="font-size:1.3rem;font-weight:800;letter-spacing:-0.5px;">Searchy</div>
      <div style="font-size:0.75rem;color:#94a3b8;margin-top:2px;">AI Job Hunting Assistant</div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # Profile summary in sidebar
    try:
        profile = load_profile()
        skill_count = len(profile.get("summary", {}).get("all_skills", []))
        st.markdown(f"""
        <div class="profile-card">
          <div style="font-size:2rem;">👤</div>
          <div class="profile-name">{profile.get('name','Unknown')}</div>
          <div class="profile-detail">{profile.get('email','')}</div>
          <div class="profile-detail" style="margin-top:6px;">
            Year {profile.get('year_of_study','?')} B.Tech
            &nbsp;|&nbsp;
            {skill_count} skills
          </div>
        </div>
        """, unsafe_allow_html=True)
    except FileNotFoundError:
        profile = None
        st.warning("⚠️ No resume uploaded yet.")

    st.markdown("### 🎛️ Filters")
    min_score = st.slider("Min Match Score", 0, 100, 40, 5)
    source_filter = st.selectbox("Source", ["All", "internshala", "linkedin", "unstop", "wellfound"])
    search_q = st.text_input("🔍 Search title/company", placeholder="e.g. Python, ML, Remote...")

    st.divider()
    st.markdown("### ⚡ Quick Actions")
    if st.button("▶️ Run Pipeline Now", use_container_width=True):
        with st.spinner("Running Searchy pipeline…"):
            try:
                from main import run_pipeline
                result = run_pipeline(send_telegram=True, send_email=False)
                st.success(f"✓ Done! Found {result.get('new',0)} new, alerted {result.get('alerted',0)}")
            except Exception as e:
                st.error(f"Pipeline error: {e}")

    if st.button("📧 Send Email Digest", use_container_width=True):
        with st.spinner("Sending digest…"):
            try:
                from notifiers.email_notifier import send_daily_digest
                jobs_for_digest = get_top_jobs(limit=20, min_score=min_score)
                ok = send_daily_digest(jobs_for_digest)
                st.success("Digest sent!" if ok else "Failed — check email config.")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.markdown(f"""
    <div style="font-size:11px;color:#475569;text-align:center;padding:4px;">
      <span class="pulse-dot"></span>Active
      &nbsp;|&nbsp;
      {datetime.now().strftime('%H:%M')}
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
#  MAIN CONTENT
# ═══════════════════════════════════════════════════════════════════════
# ── Hero header ───────────────────────────────────────────────────────
stats = get_stats()
st.markdown(f"""
<div class="hero-header">
  <h1 class="hero-title">🔍 Searchy Dashboard</h1>
  <p class="hero-sub">Your AI-powered internship & job discovery engine • Live since today</p>
</div>
""", unsafe_allow_html=True)

# ── Stats row ─────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
stat_data = [
    (c1, "📦", stats["total_jobs"],       "Total Jobs"),
    (c2, "🆕", stats["new_today"],        "New Today"),
    (c3, "🏆", f"{stats['top_match_score']:.0f}", "Top Score"),
    (c4, "🔔", stats["notified"],          "Notified"),
    (c5, "❤️", stats["saved"],             "Saved"),
]
for col, icon, value, label in stat_data:
    with col:
        st.markdown(f"""
        <div class="stat-card">
          <div class="stat-icon">{icon}</div>
          <div>
            <div class="stat-label">{label}</div>
            <div class="stat-value">{value}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────
tab_all, tab_top, tab_saved, tab_analytics, tab_profile = st.tabs([
    "🌐 All Jobs",
    "🏆 Top Matches",
    "❤️ Saved",
    "📊 Analytics",
    "👤 Profile",
])


# ══════════════════════════════════════════
#  TAB 1 — ALL JOBS
# ══════════════════════════════════════════
with tab_all:
    st.markdown('<div class="section-header">All Scraped Listings</div>', unsafe_allow_html=True)

    # ── Fetch & filter ──────────────────────────────────────────────
    src = None if source_filter == "All" else source_filter
    jobs = get_all_jobs(limit=300)

    # Apply sidebar filters
    if src:
        jobs = [j for j in jobs if j.get("source") == src]
    if search_q:
        q = search_q.lower()
        jobs = [j for j in jobs
                if q in (j.get("title") or "").lower()
                or q in (j.get("company") or "").lower()]
    jobs = [j for j in jobs if (j.get("match_score") or 0) >= min_score]

    if not jobs:
        st.markdown("""
        <div class="empty-state">
          <span class="empty-icon">🌵</span>
          <strong>No listings found</strong><br>
          <span>Run the pipeline or adjust your filters.</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Sort control
        sort_col, _, count_col = st.columns([2, 3, 2])
        with sort_col:
            sort_by = st.selectbox("Sort by", ["Match Score ↓", "Newest First", "Company A-Z"], label_visibility="collapsed")
        with count_col:
            st.markdown(f"<div style='text-align:right;color:#94a3b8;padding-top:8px;font-size:13px;'>{len(jobs)} listings</div>", unsafe_allow_html=True)

        if sort_by == "Match Score ↓":
            jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)
        elif sort_by == "Newest First":
            jobs.sort(key=lambda j: j.get("scraped_at", ""), reverse=True)
        elif sort_by == "Company A-Z":
            jobs.sort(key=lambda j: (j.get("company") or "").lower())

        for job in jobs[:50]:
            render_job_card(job, profile, show_explain=True, tab_name="all")

        if len(jobs) > 50:
            st.info(f"Showing 50 of {len(jobs)} listings. Apply filters to narrow down.")


# ══════════════════════════════════════════
#  TAB 2 — TOP MATCHES
# ══════════════════════════════════════════
with tab_top:
    st.markdown('<div class="section-header">🏆 Best AI-Matched Opportunities</div>', unsafe_allow_html=True)

    top_jobs = get_top_jobs(limit=30, min_score=60)

    if not top_jobs:
        st.markdown("""
        <div class="empty-state">
          <span class="empty-icon">🎯</span>
          <strong>No high-scoring matches yet</strong><br>
          <span>Run the pipeline to discover relevant jobs.</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Featured top job
        if top_jobs:
            best = top_jobs[0]
            st.markdown(f"""
            <div style="
              background: linear-gradient(135deg, #064e3b22, #065f4622);
              border: 2px solid #22c55e44;
              border-radius: 16px;
              padding: 24px;
              margin-bottom: 20px;
              position: relative;
            ">
              <div style="position:absolute;top:12px;right:16px;font-size:11px;
                          background:#22c55e;color:white;border-radius:6px;padding:2px 10px;font-weight:700;">
                ⭐ BEST MATCH
              </div>
              <div style="font-size:1.2rem;font-weight:800;color:#f0fdf4;">{best.get('title','?')}</div>
              <div style="color:#86efac;font-size:0.9rem;margin:4px 0 10px;">
                🏢 {best.get('company','?')} &nbsp;|&nbsp; 📍 {best.get('location','?')} &nbsp;|&nbsp; 💰 {best.get('stipend','?')}
              </div>
              <div style="font-size:2rem;font-weight:900;color:#22c55e;">{best.get('match_score',0):.0f}<span style="font-size:1rem;color:#86efac;">/100</span></div>
              <a href="{best.get('url','#')}" target="_blank" style="
                display:inline-block;margin-top:10px;
                background:#22c55e;color:white;padding:8px 20px;
                border-radius:8px;font-weight:700;text-decoration:none;font-size:14px;">
                Apply Now →
              </a>
            </div>
            """, unsafe_allow_html=True)

        for job in top_jobs:
            render_job_card(job, profile, show_explain=True, tab_name="top")


# ══════════════════════════════════════════
#  TAB 3 — SAVED
# ══════════════════════════════════════════
with tab_saved:
    st.markdown('<div class="section-header">❤️ Saved Opportunities</div>', unsafe_allow_html=True)
    saved_jobs = get_saved_jobs()

    if not saved_jobs:
        st.markdown("""
        <div class="empty-state">
          <span class="empty-icon">🗂️</span>
          <strong>No saved jobs yet</strong><br>
          <span>Hit the 🤍 Save button on any listing to track it here.</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"You have **{len(saved_jobs)}** saved listings.")
        for job in saved_jobs:
            render_job_card(job, profile, show_explain=True, tab_name="saved")


# ══════════════════════════════════════════
#  TAB 4 — ANALYTICS
# ══════════════════════════════════════════
with tab_analytics:
    st.markdown('<div class="section-header">📊 Pipeline Analytics</div>', unsafe_allow_html=True)

    all_jobs_raw = get_all_jobs(limit=500)

    if not all_jobs_raw:
        st.info("No data yet — run the pipeline first.")
    else:
        df = pd.DataFrame(all_jobs_raw)
        df["match_score"] = pd.to_numeric(df["match_score"], errors="coerce").fillna(0)
        df["scraped_at"]  = pd.to_datetime(df["scraped_at"], errors="coerce")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Score Distribution**")
            try:
                import plotly.graph_objects as go
                score_bins = [0, 30, 50, 70, 90, 100]
                labels = ["0-30", "31-50", "51-70", "71-90", "91-100"]
                counts = pd.cut(df["match_score"], bins=score_bins, labels=labels).value_counts().sort_index()
                colors = ["#475569", "#6b7280", "#3b82f6", "#22c55e", "#f59e0b"]
                fig = go.Figure(go.Bar(
                    x=counts.index.tolist(),
                    y=counts.values.tolist(),
                    marker_color=colors[:len(counts)],
                    text=counts.values.tolist(),
                    textposition="outside",
                ))
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#f1f5f9",
                    showlegend=False,
                    margin=dict(t=20, b=20, l=0, r=0),
                    height=260,
                    xaxis=dict(gridcolor="#334155"),
                    yaxis=dict(gridcolor="#334155"),
                )
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.bar_chart(df["match_score"].value_counts(bins=10).sort_index())

        with col2:
            st.markdown("**Jobs by Source**")
            if "source" in df.columns:
                src_counts = df["source"].value_counts()
                try:
                    import plotly.graph_objects as go
                    fig2 = go.Figure(go.Pie(
                        labels=src_counts.index.tolist(),
                        values=src_counts.values.tolist(),
                        hole=0.5,
                        marker=dict(colors=["#3b82f6","#22c55e","#f59e0b","#a855f7"]),
                    ))
                    fig2.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        font_color="#f1f5f9",
                        showlegend=True,
                        margin=dict(t=20, b=20, l=0, r=0),
                        height=260,
                    )
                    st.plotly_chart(fig2, use_container_width=True)
                except ImportError:
                    st.bar_chart(src_counts)

        # Timeline
        st.markdown("**Jobs Discovered Over Time**")
        if "scraped_at" in df.columns and df["scraped_at"].notna().any():
            try:
                timeline = df.groupby(df["scraped_at"].dt.date).size().reset_index()
                timeline.columns = ["Date", "Count"]
                import plotly.graph_objects as go
                fig3 = go.Figure(go.Scatter(
                    x=timeline["Date"], y=timeline["Count"],
                    mode="lines+markers",
                    line=dict(color="#3b82f6", width=2.5),
                    marker=dict(size=7, color="#60a5fa"),
                    fill="tozeroy",
                    fillcolor="rgba(59,130,246,0.1)",
                ))
                fig3.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#f1f5f9",
                    margin=dict(t=10, b=20, l=0, r=0),
                    height=220,
                    xaxis=dict(gridcolor="#334155"),
                    yaxis=dict(gridcolor="#334155"),
                )
                st.plotly_chart(fig3, use_container_width=True)
            except ImportError:
                st.line_chart(df.set_index("scraped_at")["match_score"])

        # Top companies table
        st.markdown("**Top Companies by Listing Count**")
        if "company" in df.columns:
            top_companies = df["company"].value_counts().head(10).reset_index()
            top_companies.columns = ["Company", "Listings"]
            st.dataframe(
                top_companies,
                use_container_width=True,
                hide_index=True,
            )


# ══════════════════════════════════════════
#  TAB 5 — PROFILE
# ══════════════════════════════════════════
with tab_profile:
    st.markdown('<div class="section-header">👤 Your Profile</div>', unsafe_allow_html=True)

    # Upload new resume
    st.markdown("#### 📄 Upload / Update Resume")
    uploaded = st.file_uploader("Drop your PDF resume here", type=["pdf"], label_visibility="collapsed")

    if uploaded:
        tmp_path = ROOT / "tmp_resume.pdf"
        with open(tmp_path, "wb") as f:
            f.write(uploaded.read())
        with st.spinner("Parsing resume…"):
            try:
                new_profile = parse_resume(str(tmp_path))
                save_profile(new_profile)
                tmp_path.unlink(missing_ok=True)
                st.success(f"✅ Profile updated for {new_profile['name']}!")
                st.rerun()
            except Exception as e:
                st.error(f"Parse error: {e}")
                tmp_path.unlink(missing_ok=True)

    if profile:
        c1, c2 = st.columns([1, 2])

        with c1:
            st.markdown(f"""
            <div class="profile-card" style="text-align:left;padding:24px;">
              <div style="font-size:2.5rem;margin-bottom:8px;">👤</div>
              <div style="font-size:1.3rem;font-weight:800;">{profile.get('name','?')}</div>
              <div style="color:#94a3b8;font-size:0.85rem;margin:4px 0;">
                📧 {profile.get('email','N/A')}<br>
                📱 {profile.get('phone','N/A')}<br>
                🎓 Year {profile.get('year_of_study','?')} B.Tech<br>
                📊 CGPA: {profile.get('cgpa','N/A')}
              </div>
            """, unsafe_allow_html=True)
            links = profile.get("links", {})
            for platform, url in links.items():
                st.markdown(f'<a href="{url}" target="_blank" class="pill-btn" style="margin:3px 0;display:inline-block;font-size:12px;">{platform.title()} ↗</a>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with c2:
            st.markdown("**🛠️ Technical Skills**")
            tech_skills = profile.get("skills", {}).get("technical", [])
            soft_skills = profile.get("skills", {}).get("soft", [])
            tags_html = "".join(f'<span class="tag">{s}</span>' for s in tech_skills)
            st.markdown(f'<div style="margin-bottom:16px;">{tags_html}</div>', unsafe_allow_html=True)

            if soft_skills:
                st.markdown("**🤝 Soft Skills**")
                soft_html = "".join(
                    f'<span class="tag" style="background:rgba(168,85,247,0.15);color:#c084fc;">{s}</span>'
                    for s in soft_skills
                )
                st.markdown(f'<div style="margin-bottom:16px;">{soft_html}</div>', unsafe_allow_html=True)

            edu = profile.get("education", [])
            if edu:
                st.markdown("**🎓 Education**")
                for e in edu:
                    st.markdown(f"• **{e.get('degree','')}** — {e.get('institution','')}" +
                                (f" ({e['year']})" if e.get("year") else ""))

            projs = profile.get("projects", [])
            if projs:
                st.markdown(f"**🚀 Projects ({len(projs)})**")
                for p in projs[:5]:
                    st.markdown(f"• {p[:120]}")

        # Raw JSON
        with st.expander("🔧 Raw profile.json"):
            st.json(profile)
    else:
        st.info("Upload your resume above to get started!")