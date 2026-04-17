"""
resume_parser.py — JobSearchy Resume Parser v2
Supports: PDF, DOCX, DOC
Extracts: name, email, phone, skills, education, year of study, projects,
          experience, certifications → saves as profile.json

v2 improvements (Apr 17, 2026):
  • Skill INFERENCE from project descriptions, experience bullets, and certs
  • Confidence weighting per skill (explicit=1.0, experience=0.9, project=0.8, cert=0.7)
  • Structured projects: title + description + inferred skills
  • Structured experience: company + role + duration + inferred skills
  • Structured certifications: name + issuer + inferred skills
  • Expanded TECH_SKILLS dictionary (~250 skills, up from ~80)
  • Portfolio link detection (github.io, vercel.app, netlify.app)
"""

import re
import json
import sys
import datetime
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
    PDF_BACKEND = "pdfplumber"
except ImportError:
    try:
        from pypdf import PdfReader
        PDF_BACKEND = "pypdf"
    except ImportError:
        PDF_BACKEND = None

try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profile.json"

TECH_SKILLS = {
    "python","java","c","c++","c#","javascript","typescript","go","golang","rust",
    "kotlin","swift","r","matlab","scala","php","ruby","dart","bash","shell","perl",
    "html","css","react","angular","vue","next.js","nextjs","nuxt","svelte",
    "bootstrap","tailwind","sass","scss","redux","jquery","webpack","vite",
    "django","flask","fastapi","spring","spring boot","express","node.js","nodejs",
    "nestjs","rails","asp.net",".net","laravel",
    "rest","restful","graphql","grpc","websocket","soap","api","jwt","oauth",
    "pandas","numpy","matplotlib","seaborn","scikit-learn","sklearn","scipy",
    "tensorflow","pytorch","keras","opencv","nltk","spacy","huggingface",
    "transformers","langchain","llm","llms","rag","openai","anthropic","claude",
    "machine learning","deep learning","data science","nlp","computer vision",
    "reinforcement learning","generative ai","genai","ml","ai",
    "xgboost","lightgbm","catboost","random forest","logistic regression",
    "linear regression","decision tree","svm","knn","k-means","clustering",
    "classification","regression","time series","forecasting","arima",
    "neural network","cnn","rnn","lstm","gru","transformer","bert","gpt",
    "attention","embedding","feature engineering","hyperparameter tuning",
    "cross-validation","grid search","random search","auc","roc","f1","precision","recall",
    "mysql","postgresql","postgres","sqlite","mongodb","redis","firebase",
    "cassandra","elasticsearch","dynamodb","sql","nosql","oracle","mariadb","supabase",
    "aws","gcp","azure","heroku","vercel","netlify","render","railway",
    "docker","kubernetes","k8s","terraform","ansible","puppet","chef",
    "jenkins","github actions","gitlab ci","circleci","ci/cd",
    "linux","ubuntu","unix","git","github","gitlab","bitbucket",
    "android","ios","flutter","react native","xamarin","ionic",
    "blockchain","web3","solidity","arduino","raspberry pi","embedded","iot","vlsi",
    "selenium","playwright","cypress","beautifulsoup","scrapy","requests","puppeteer",
    "excel","tableau","power bi","powerbi","figma","canva","ms office",
    "shap","smote","gradio","streamlit","jupyter","colab","google colab",
    "statsmodels","plotly","augmented dickey-fuller","adf","ols","econometrics",
    "imbalanced-learn","dash","bokeh","altair","vega","d3.js","d3",
    "airflow","dbt","spark","pyspark","hadoop","hive","kafka","rabbitmq",
    "mlflow","weights & biases","wandb","tensorboard","optuna","ray",
    "pytest","unittest","junit","jest","mocha","jasmine",
    "postman","insomnia","swagger","openapi",
    "data analysis","data visualisation","data visualization","data engineering",
    "business intelligence","bi","dashboard","reporting","research",
    "survey design","literature review","data collection","quantitative research",
    "microsoft excel","google sheets","microsoft word","google docs",
    "a/b testing","hypothesis testing","statistical analysis","anova",
    "customer segmentation","cohort analysis","funnel analysis",
    "predictive modeling","propensity modeling","churn prediction",
}

SOFT_SKILLS = {
    "communication","leadership","teamwork","problem solving","problem-solving",
    "time management","critical thinking","collaboration","creativity",
    "adaptability","presentation","analytical thinking","decision making",
    "project management","agile","scrum","kanban",
}

EDUCATION_KEYWORDS = [
    "b.tech","btech","b.e","be","bachelor","m.tech","mtech",
    "m.e","me","master","mba","bsc","b.sc","msc","m.sc",
    "phd","ph.d","diploma","10th","12th","ssc","hsc",
    "university","college","institute","iit","nit","bits",
]


# ── Text extraction ──────────────────────────────────────────────────────────

def extract_text_from_pdf(path: str) -> str:
    if PDF_BACKEND == "pdfplumber":
        import pdfplumber
        parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=2, y_tolerance=2)
                if t:
                    parts.append(t)
        return "\n".join(parts)
    elif PDF_BACKEND == "pypdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        raise ImportError("Install pdfplumber: pip install pdfplumber")


def extract_text_from_docx(path: str) -> str:
    if not DOCX_AVAILABLE:
        raise ImportError("Install python-docx: pip install python-docx")
    doc = DocxDocument(path)
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())
    return "\n".join(parts)


def extract_text_from_doc(path: str) -> str:
    try:
        import subprocess
        result = subprocess.run(
            ["antiword", path], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception:
        pass
    try:
        return extract_text_from_docx(path)
    except Exception:
        pass
    raise ValueError("Could not read .doc file. Please convert to PDF or DOCX.")


def extract_text(file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    ext = path.suffix.lower()
    if ext == ".pdf":
        text = extract_text_from_pdf(file_path)
        if not text.strip():
            raise ValueError("Could not extract text from PDF (scanned image?).")
        return text
    elif ext == ".docx":
        text = extract_text_from_docx(file_path)
        if not text.strip():
            raise ValueError("Could not extract text from DOCX.")
        return text
    elif ext == ".doc":
        text = extract_text_from_doc(file_path)
        if not text.strip():
            raise ValueError("Could not extract text from DOC.")
        return text
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def extract_text_from_pdf_compat(pdf_path: str) -> str:
    return extract_text(pdf_path)


# ── Personal info extractors ─────────────────────────────────────────────────

def extract_college(text: str) -> Optional[str]:
    lines = text.splitlines()
    college_keywords = [
        "university", "college", "institute", "iit", "nit", "bits",
        "mit", "vitb", "vit", "lpu", "srm", "amity", "manipal",
        "engineering", "technology", "trinity",
    ]
    skip_patterns = [
        r"research|analytics|econometrics|quantitative|data science",
        r"python|java|react|sql|cgpa|score|marks|percent",
        r"^\s*[\·\|•\-]",
    ]
    for line in lines:
        l = line.strip()
        if not l or len(l) < 8 or len(l) > 120:
            continue
        ll = l.lower()
        if not any(kw in ll for kw in college_keywords):
            continue
        if any(re.search(p, ll) for p in skip_patterns):
            continue
        if not re.search(r"[A-Z][a-z]{2,}", l):
            continue
        return l[:120]
    return None


def extract_current_course(text: str) -> Optional[str]:
    patterns = [
        r"(b\.?tech|b\.?e|bachelor of technology|bachelor of engineering)[^\n]*?(computer science|cs|it|information technology|electronics|electrical|mechanical|civil|entc|telecommunication|data science|ai|artificial intelligence|machine learning)[^\n]*",
        r"(b\.?e\.?)[^\n]*?(electronics|telecommunication|entc|electrical|mechanical)[^\n]*",
        r"(m\.?tech|master of technology|mba|b\.?sc|m\.?sc)[^\n]*?(computer|data|software|electronics|physics|mathematics|ai|machine learning)[^\n]*",
        r"(b\.?tech|b\.?e|m\.?tech|mba|b\.?sc|m\.?sc|phd)[^\n]{0,60}",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result = m.group(0).strip()
            if len(result) > 5:
                return result[:100]
    return None


def extract_name(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 3:
            continue
        if re.search(r"[@://\d\|]", line):
            continue
        if any(kw in line.lower() for kw in ["resume","curriculum","cv","profile"]):
            continue
        words = line.split()
        if 2 <= len(words) <= 5 and all(re.match(r"^[A-Za-z][a-zA-Z'-]*$", w) for w in words):
            return line.title()
    return "Unknown"


def extract_email(text: str) -> Optional[str]:
    m = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return m.group(0).lower() if m else None


def extract_phone(text: str) -> Optional[str]:
    m = re.search(
        r"(?:\+91[\s\-]?)?(?:\(?[6-9]\d{4}\)?[\s\-]?\d{5}|\d{10})",
        text.replace(" ", ""),
    )
    if m:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) in (10, 12):
            return "+" + digits if len(digits) == 12 else digits
    return None


def extract_links(text: str) -> dict:
    links = {}
    gh = re.search(r"github\.com/[\w\-]+", text, re.IGNORECASE)
    if gh:
        links["github"] = "https://" + gh.group(0).rstrip("/")
    li = re.search(r"linkedin\.com/in/[\w\-]+", text, re.IGNORECASE)
    if li:
        links["linkedin"] = "https://" + li.group(0).rstrip("/")
    # Portfolio (personal domain)
    portfolio_patterns = [
        r"https?://[\w\-]+\.(?:github\.io|vercel\.app|netlify\.app|pages\.dev)(?:/[\w\-/]*)?",
    ]
    for pat in portfolio_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            url = m.group(0).rstrip("/").strip()
            if "linkedin" not in url.lower() and "github.com" not in url.lower():
                links["portfolio"] = url
                break
    return links


# ── Skill inference (v2 KEY FEATURE) ─────────────────────────────────────────

def _find_skills_in_text(text: str) -> set:
    """Find every known tech skill in arbitrary text. Returns set of lowercase skill names."""
    lower = text.lower()
    found = set()
    for skill in TECH_SKILLS:
        if re.search(r"\b" + re.escape(skill) + r"\b", lower):
            found.add(skill)
    return found


def extract_skills(text: str) -> dict:
    lower = text.lower()
    tech = sorted({s for s in TECH_SKILLS if re.search(r"\b" + re.escape(s) + r"\b", lower)})
    soft = sorted({s for s in SOFT_SKILLS if re.search(r"\b" + re.escape(s) + r"\b", lower)})
    return {"technical": tech, "soft": soft}


def _find_section(text: str, start_keywords: list, stop_keywords: list) -> list:
    lines = text.splitlines()
    result = []
    inside = False
    start_re = re.compile(r"^\s*(" + "|".join(start_keywords) + r")\b", re.IGNORECASE)
    stop_re  = re.compile(r"^\s*(" + "|".join(stop_keywords)  + r")\b", re.IGNORECASE)
    for line in lines:
        s = line.strip()
        if start_re.match(s):
            inside = True
            continue
        if inside and stop_re.match(s):
            inside = False
        if inside and s:
            result.append(s)
    return result


def _extract_section_blocks(text: str, start_keywords: list, stop_keywords: list) -> list:
    """Groups consecutive lines into blocks; each block likely = one project/job/cert."""
    lines = _find_section(text, start_keywords, stop_keywords)
    blocks, current = [], []
    for line in lines:
        is_new_block = (
            len(current) > 0
            and len(line) < 80
            and len(line.split()) <= 10
            and re.match(r"^[A-Z][A-Za-z]", line)
            and not line.startswith(("•", "-", "*", "○", "▪"))
        )
        if is_new_block:
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


# ── Structured extractors with skill inference ──────────────────────────────

def extract_education(text: str) -> list:
    edu_lines = _find_section(
        text,
        ["education","academic","qualification"],
        ["experience","project","skill","certif","award","extra","activit","interest","volunteer"],
    )
    if not edu_lines:
        for line in text.splitlines():
            if any(kw in line.lower() for kw in EDUCATION_KEYWORDS):
                edu_lines.append(line.strip())

    entries, seen = [], set()
    not_edu_patterns = [
        r'\[github\]', r'github\.com', r'http', r'analysed', r'analyzed',
        r'developed', r'built', r'created', r'led', r'predicted', r'implemented',
        r'restaurant|market|membership|customer|upgrade|propensity',
        r'\(cid:', r'locality|localities|statistical testing',
    ]
    for line in edu_lines:
        if not line or line in seen:
            continue
        if any(re.search(p, line, re.IGNORECASE) for p in not_edu_patterns):
            continue
        seen.add(line)
        deg = re.search(
            r"(b\.?tech|b\.?e|bachelor|m\.?tech|master|mba|b\.?sc|m\.?sc|phd|diploma)",
            line, re.IGNORECASE
        )
        yr = re.search(r"\b(20\d{2})\b", line)
        if deg or any(kw in line.lower() for kw in ["university","college","institute","school"]):
            entries.append({
                "institution": line[:120],
                "degree":      deg.group(0).upper() if deg else None,
                "year":        int(yr.group(0)) if yr else None,
            })
    return entries[:4]


def extract_year_of_study(text: str) -> Optional[int]:
    YEAR_MAP = {
        "1st":1,"first":1,"1":1, "2nd":2,"second":2,"2":2,
        "3rd":3,"third":3,"3":3, "4th":4,"fourth":4,"4":4,
    }
    lower = text.lower()
    patterns = [
        r"(\d)(?:st|nd|rd|th)\s+year",
        r"year\s+(\d)",
        r"(first|second|third|fourth)\s+year",
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            result = YEAR_MAP.get(m.group(1).lower())
            if result:
                return result
    range_match = re.search(r"(20\d{2})\s*[\u2013\-–]+\s*(20\d{2})", text)
    if range_match:
        start_year = int(range_match.group(1))
        current_year = datetime.datetime.now().year
        years_done = current_year - start_year
        return min(max(years_done, 1), 4)
    return None


def extract_cgpa(text: str) -> Optional[float]:
    m = re.search(r"(?:cgpa|gpa|cpi)[^\d]*(\d+\.\d+)", text, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        return round(val, 2) if val <= 10.0 else None
    return None


def extract_projects(text: str) -> list:
    """v2: Returns structured project dicts with inferred skills."""
    blocks = _extract_section_blocks(
        text,
        ["project","projects","academic project","key project"],
        ["education","academic","experience","skill","certif","award","extra","activit","volunteer","interest"],
    )
    result = []
    for block in blocks:
        if not block:
            continue
        title = block[0][:120] if block[0] else ""
        description = " ".join(block[1:])[:800] if len(block) > 1 else ""
        full_text = title + " " + description
        if len(full_text.strip()) < 10:
            continue
        inferred = sorted(_find_skills_in_text(full_text))
        result.append({
            "title":           title.strip(),
            "description":     description.strip(),
            "inferred_skills": inferred,
        })
    return result[:8]


def extract_experience(text: str) -> list:
    """v2: Returns structured experience dicts with inferred skills."""
    blocks = _extract_section_blocks(
        text,
        ["experience","internship","internships","work history","work experience","professional experience"],
        ["education","project","skill","certif","award","extra","activit","volunteer","interest"],
    )
    result = []
    for block in blocks:
        if not block:
            continue
        header = block[0]
        description = " ".join(block[1:])[:800] if len(block) > 1 else ""

        role = company = duration = ""
        sep = re.split(r"\s*[\|\–\-]\s+|\s+at\s+|\s*,\s+", header, maxsplit=3)
        if len(sep) >= 2:
            role = sep[0].strip()
            company = sep[1].strip()
            if len(sep) >= 3:
                duration = sep[2].strip()
        else:
            role = header.strip()

        full_text = header + " " + description
        inferred = sorted(_find_skills_in_text(full_text))
        if len(full_text.strip()) < 10:
            continue
        result.append({
            "role":            role[:100],
            "company":         company[:100],
            "duration":        duration[:50],
            "description":     description.strip(),
            "inferred_skills": inferred,
        })
    return result[:6]


def extract_certifications(text: str) -> list:
    """v2: Returns structured cert dicts with inferred skills."""
    lines = _find_section(
        text,
        ["certif","course","training","achievement","award"],
        ["education","experience","project","skill","extra","activit","volunteer","interest"],
    )
    result = []
    for line in lines:
        if len(line) < 5:
            continue
        sep = re.split(r"\s*[\|\–\-]\s+|\s+by\s+|\s+from\s+", line, maxsplit=1)
        name = sep[0].strip()
        issuer = sep[1].strip() if len(sep) > 1 else ""
        inferred = sorted(_find_skills_in_text(line))
        result.append({
            "name":            name[:150],
            "issuer":          issuer[:80],
            "inferred_skills": inferred,
        })
    return result[:10]


# ── Domain detection ─────────────────────────────────────────────────────────

def detect_domain(text: str, skills: list) -> str:
    lower = text.lower()
    skill_set = {s.lower() for s in skills}
    scores = {"aiml": 0, "datascience": 0, "webdev": 0, "devops": 0, "research": 0, "entc": 0}

    scores["aiml"]        += len(skill_set & {"machine learning","deep learning","tensorflow","pytorch","keras","xgboost","nlp","computer vision","huggingface","scikit-learn","sklearn","llm","langchain","transformers"}) * 2
    scores["datascience"] += len(skill_set & {"pandas","numpy","data analysis","data science","tableau","power bi","statistics","econometrics","statsmodels","scipy","r","excel","data visualization","data visualisation"}) * 2
    scores["webdev"]      += len(skill_set & {"react","angular","vue","node.js","nodejs","express","django","flask","fastapi","html","css","javascript","typescript","graphql","rest","api"}) * 2
    scores["devops"]      += len(skill_set & {"docker","kubernetes","aws","gcp","azure","terraform","ansible","jenkins","linux","bash","ci/cd","github actions"}) * 2
    scores["research"]    += len(skill_set & {"research","econometrics","statsmodels","ols","adf","scipy","survey design","literature review","data collection"}) * 2
    scores["entc"]        += len(skill_set & {"arduino","raspberry pi","embedded","verilog","matlab","iot","vlsi"}) * 2

    if any(k in lower for k in ["artificial intelligence","machine learning","deep learning","ai/ml","ai & ml","aiml"]):
        scores["aiml"] += 3
    if any(k in lower for k in ["data science","data analyst","business intelligence","analytics"]):
        scores["datascience"] += 3
    if any(k in lower for k in ["web development","full stack","fullstack","frontend","backend","software engineer"]):
        scores["webdev"] += 3
    if any(k in lower for k in ["devops","cloud","infrastructure","devsecops","site reliability"]):
        scores["devops"] += 3
    if any(k in lower for k in ["research","econometrics","quantitative","publication","paper","rbi","isro"]):
        scores["research"] += 3
    if any(k in lower for k in ["electronics","telecommunication","entc","embedded","vlsi","iot","circuit"]):
        scores["entc"] += 3

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "datascience"


# ── Weighted skill aggregation (v2 KEY FEATURE) ─────────────────────────────

def build_weighted_skills(explicit_skills: list, projects: list,
                          experience: list, certifications: list) -> dict:
    """
    Aggregates skills from all sources with confidence weights:
      - Explicit skill in Skills section       → 1.00
      - Skill inferred from experience bullets → 0.90  (real usage)
      - Skill inferred from project            → 0.80  (self-directed)
      - Skill inferred from certification      → 0.70  (learned, maybe not used)
    Returns: {weighted, all_skills, sources}
    """
    weighted: dict = {}
    sources: dict = {}

    def add(skill: str, weight: float, source: str):
        s = skill.lower().strip()
        if not s:
            return
        if s not in weighted or weight > weighted[s]:
            weighted[s] = weight
        sources.setdefault(s, []).append(source)

    for s in explicit_skills:
        add(s, 1.0, "explicit")
    for exp in experience or []:
        label = f"experience:{exp.get('company','') or exp.get('role','') or 'work'}"[:60]
        for s in exp.get("inferred_skills", []):
            add(s, 0.90, label)
    for proj in projects or []:
        label = f"project:{proj.get('title', '')[:40]}"
        for s in proj.get("inferred_skills", []):
            add(s, 0.80, label)
    for cert in certifications or []:
        label = f"cert:{cert.get('name', '')[:40]}"
        for s in cert.get("inferred_skills", []):
            add(s, 0.70, label)

    return {
        "weighted":   weighted,
        "all_skills": sorted(weighted.keys()),
        "sources":    sources,
    }


# ── Main parse function ──────────────────────────────────────────────────────

def parse_resume(file_path: str) -> dict:
    print(f"[JobSearchy] Parsing resume: {file_path}")
    raw_text = extract_text(file_path)

    name = extract_name(raw_text)
    email = extract_email(raw_text)
    phone = extract_phone(raw_text)
    links = extract_links(raw_text)

    education = extract_education(raw_text)
    college = extract_college(raw_text)
    current_course = extract_current_course(raw_text)
    year = extract_year_of_study(raw_text)
    cgpa = extract_cgpa(raw_text)

    explicit = extract_skills(raw_text)
    explicit_all = explicit["technical"] + explicit["soft"]

    projects = extract_projects(raw_text)
    experience = extract_experience(raw_text)
    certifications = extract_certifications(raw_text)

    weighted = build_weighted_skills(explicit_all, projects, experience, certifications)
    all_skills_flat = weighted["all_skills"]

    domain = detect_domain(raw_text, all_skills_flat)

    return {
        "source_file":     str(Path(file_path).resolve()),
        "parsed_at":       datetime.datetime.utcnow().isoformat() + "Z",
        "name":            name,
        "email":           email,
        "phone":           phone,
        "links":           links,
        "skills":          all_skills_flat,
        "skills_weighted": weighted["weighted"],
        "skills_sources":  weighted["sources"],
        "skills_explicit": sorted(explicit_all),
        "education":       education,
        "college":         college,
        "current_course":  current_course,
        "domain":          domain,
        "year_of_study":   year,
        "cgpa":            cgpa,
        "projects":        projects,
        "experience":      experience,
        "certifications":  certifications,
        "summary": {
            "all_skills":     all_skills_flat,
            "num_explicit":   len(explicit_all),
            "num_inferred":   max(0, len(all_skills_flat) - len(explicit_all)),
            "has_experience": len(experience) > 0,
            "num_projects":   len(projects),
            "num_certs":      len(certifications),
        },
    }


def save_profile(profile: dict, output_path: Optional[str] = None) -> str:
    out = Path(output_path) if output_path else PROFILE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    print(f"[JobSearchy] Profile saved → {out}")
    return str(out)


def load_profile(path: Optional[str] = None) -> dict:
    p = Path(path) if path else PROFILE_PATH
    if not p.exists():
        raise FileNotFoundError(f"No profile at {p}. Run parse_resume() first.")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python resume_parser.py <resume.pdf|resume.docx> [output.json]")
        sys.exit(1)
    profile = parse_resume(sys.argv[1])
    saved = save_profile(profile, sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"\n✓ Name:     {profile['name']}")
    print(f"✓ Email:    {profile['email']}")
    print(f"✓ College:  {profile['college']}")
    print(f"✓ Course:   {profile['current_course']}")
    print(f"✓ Year:     {profile['year_of_study']}")
    print(f"✓ CGPA:     {profile['cgpa']}")
    print(f"✓ Skills:   {len(profile['skills'])} total "
          f"({profile['summary']['num_explicit']} explicit, "
          f"{profile['summary']['num_inferred']} inferred)")
    print(f"✓ Projects: {profile['summary']['num_projects']}")
    print(f"✓ Exp:      {len(profile['experience'])}")
    print(f"✓ Certs:    {profile['summary']['num_certs']}")
    print(f"✓ Domain:   {profile['domain']}")
    print(f"✓ Saved →   {saved}")
