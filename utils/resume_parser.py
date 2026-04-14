"""
resume_parser.py — JobSearchy Resume Parser
Supports: PDF, DOCX, DOC
Extracts: name, email, phone, skills, education, year of study,
          projects, experience, certifications → saves as profile.json
"""

import re
import json
import sys
import datetime
from pathlib import Path
from typing import Optional

# ── PDF backends ─────────────────────────────────────────────────────────────
try:
    import pdfplumber
    PDF_BACKEND = "pdfplumber"
except ImportError:
    try:
        from pypdf import PdfReader
        PDF_BACKEND = "pypdf"
    except ImportError:
        PDF_BACKEND = None

# ── DOCX backend ──────────────────────────────────────────────────────────────
try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profile.json"

TECH_SKILLS = {
    "python","java","c","c++","c#","javascript","typescript","go","rust",
    "kotlin","swift","r","matlab","scala","php","ruby","dart","bash",
    "html","css","react","angular","vue","next.js","nuxt","svelte",
    "django","flask","fastapi","spring","express","node.js","nodejs",
    "bootstrap","tailwind","sass","graphql","rest","api",
    "pandas","numpy","matplotlib","seaborn","scikit-learn","sklearn",
    "tensorflow","pytorch","keras","opencv","nltk","spacy","huggingface",
    "transformers","langchain","llm","machine learning","deep learning",
    "data science","nlp","computer vision","reinforcement learning",
    "xgboost","lightgbm","catboost",
    "mysql","postgresql","sqlite","mongodb","redis","firebase",
    "cassandra","elasticsearch","dynamodb",
    "aws","gcp","azure","docker","kubernetes","terraform","ansible",
    "jenkins","github actions","ci/cd","linux","git","github",
    "android","ios","flutter","react native",
    "blockchain","web3","solidity","arduino","raspberry pi",
    "selenium","playwright","beautifulsoup","scrapy",
    "excel","tableau","power bi","figma","shap","smote","gradio",
    "statsmodels","plotly","scipy","augmented dickey-fuller","adf",
    "ols","econometrics","imbalanced-learn","colab","jupyter","streamlit",
    "data analysis","data visualisation","data visualization",
    "business intelligence","bi","dashboard","report writing",
    "research","survey design","literature review","data collection",
    "microsoft excel","google sheets","canva","ms office",
}

SOFT_SKILLS = {
    "communication","leadership","teamwork","problem solving",
    "time management","critical thinking","collaboration","creativity",
    "adaptability","presentation",
}

EDUCATION_KEYWORDS = [
    "b.tech","btech","b.e","be","bachelor","m.tech","mtech",
    "m.e","me","master","mba","bsc","b.sc","msc","m.sc",
    "phd","ph.d","diploma","10th","12th","ssc","hsc",
    "university","college","institute","iit","nit","bits",
]


# ── Text extraction ───────────────────────────────────────────────────────────

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
    # Also extract from tables (skills tables, education tables)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())
    return "\n".join(parts)


def extract_text_from_doc(path: str) -> str:
    """Try to extract text from old .doc format using antiword or textract."""
    try:
        import subprocess
        result = subprocess.run(
            ["antiword", path], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception:
        pass
    # Fallback: try python-docx anyway (sometimes works)
    try:
        return extract_text_from_docx(path)
    except Exception:
        pass
    raise ValueError("Could not read .doc file. Please convert to PDF or DOCX.")


def extract_text(file_path: str) -> str:
    """
    Main text extractor — routes to correct backend based on file extension.
    Supports: .pdf, .docx, .doc
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()

    if ext == ".pdf":
        text = extract_text_from_pdf(file_path)
        if not text.strip():
            raise ValueError(
                "Could not extract text from PDF. "
                "If it's a scanned image PDF, please export as DOCX or use a text-based PDF."
            )
        return text

    elif ext == ".docx":
        text = extract_text_from_docx(file_path)
        if not text.strip():
            raise ValueError("Could not extract text from DOCX file.")
        return text

    elif ext == ".doc":
        text = extract_text_from_doc(file_path)
        if not text.strip():
            raise ValueError("Could not extract text from DOC file.")
        return text

    else:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            "Please upload a PDF, DOCX, or DOC file."
        )


# Keep backward compat — old code calls extract_text_from_pdf directly
def extract_text_from_pdf_compat(pdf_path: str) -> str:
    return extract_text(pdf_path)


# ── Extractors ────────────────────────────────────────────────────────────────

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
        r"(b\.?tech|b\.?e|bachelor of technology|bachelor of engineering)[^\n]*?(computer science|cs|it|information technology|electronics|electrical|mechanical|civil|entc|telecommunication|data science|ai)[^\n]*",
        r"(b\.?e\.?)[^\n]*?(electronics|telecommunication|entc|electrical|mechanical)[^\n]*",
        r"(m\.?tech|master of technology|mba|b\.?sc|m\.?sc)[^\n]*?(computer|data|software|electronics|physics|mathematics)[^\n]*",
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
    return links


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
        "1st":1,"first":1,"1":1,
        "2nd":2,"second":2,"2":2,
        "3rd":3,"third":3,"3":3,
        "4th":4,"fourth":4,"4":4,
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
        start_year   = int(range_match.group(1))
        current_year = datetime.datetime.now().year
        years_done   = current_year - start_year
        return min(max(years_done, 1), 4)
    return None


def extract_cgpa(text: str) -> Optional[float]:
    m = re.search(r"(?:cgpa|gpa|cpi)[^\d]*(\d+\.\d+)", text, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        return round(val, 2) if val <= 10.0 else None
    return None


def extract_projects(text: str) -> list:
    lines = _find_section(
        text,
        ["project","projects","academic project","key project"],
        ["education","academic","experience","skill","certif","award","extra","activit","volunteer","interest"],
    )
    result = []
    for l in lines:
        if not l or len(l) < 8:
            continue
        if re.search(r"\(cid:|^[·•\-]\s*$", l):
            continue
        result.append(l[:200])
    return result[:8]


def extract_experience(text: str) -> list:
    lines = _find_section(
        text,
        ["experience","internship","work history"],
        ["education","project","skill","certif","award","extra","activit","volunteer","interest"],
    )
    return [l[:250] for l in lines if len(l) > 5][:10]


def extract_certifications(text: str) -> list:
    lines = _find_section(
        text,
        ["certif","course","training","achievement","award"],
        ["education","experience","project","skill","extra","activit","volunteer","interest"],
    )
    return [l[:200] for l in lines if len(l) > 5][:10]


# ── Main parse function ───────────────────────────────────────────────────────

def parse_resume(file_path: str) -> dict:
    """
    Full pipeline: PDF / DOCX / DOC → structured profile dict.
    """
    print(f"[JobSearchy] Parsing resume: {file_path}")
    raw_text = extract_text(file_path)

    skills    = extract_skills(raw_text)
    education = extract_education(raw_text)
    projects  = extract_projects(raw_text)
    experience = extract_experience(raw_text)

    # Flatten skills to a single list for the scorer
    all_skills_flat = skills["technical"] + skills["soft"]

    profile = {
        "source_file":    str(Path(file_path).resolve()),
        "name":           extract_name(raw_text),
        "email":          extract_email(raw_text),
        "phone":          extract_phone(raw_text),
        "links":          extract_links(raw_text),
        "skills":         all_skills_flat,          # flat list — scorer expects this
        "education":      education,
        "college":        extract_college(raw_text),
        "current_course": extract_current_course(raw_text),
        "year_of_study":  extract_year_of_study(raw_text),
        "cgpa":           extract_cgpa(raw_text),
        "projects":       projects,
        "experience":     experience,
        "certifications": extract_certifications(raw_text),
        "summary": {
            "all_skills":     all_skills_flat,
            "has_experience": len(experience) > 0,
            "num_projects":   len(projects),
        },
    }
    return profile


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
    saved   = save_profile(profile, sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"\n✓ Name:   {profile['name']}")
    print(f"✓ Email:  {profile['email']}")
    print(f"✓ Skills ({len(profile['skills'])}): {profile['skills'][:8]}")
    print(f"✓ Year:   {profile['year_of_study']}")
    print(f"✓ Saved → {saved}")
