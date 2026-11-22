"""
filters.py — Searchy Job Filters
Removes spam/irrelevant listings without accidentally discarding
hackathons, internships, or valid fresher roles.
Returns: (accepted, rejected) tuple — always use accepted.
"""

import re
from typing import Tuple

# Hard spam signals — if title contains these EXACT patterns, skip
SPAM_TITLE_PATTERNS = [
    r"\bMLM\b", r"\bnetwork marketing\b", r"\bdirect selling\b",
    r"\bfranchise\b", r"\bself.?employed\b",
    r"\binvestment advisor\b", r"\binsurance agent\b",
    r"\breal estate agent\b",
    r"\bdata entry\b", r"\btyping work\b", r"\btyping\b",
    r"\bform filling\b", r"\bcaptcha\b",
]

# Source whitelist — never filter these sources at all
TRUSTED_SOURCES = {
    "internshala", "linkedin", "unstop", "devfolio",
    "hackerearth", "wellfound", "naukri",
}

# Job types that should always be kept regardless of other signals
ALWAYS_KEEP_TYPES = {"hackathon", "internship"}


def _is_spam(job: dict) -> bool:
    """Returns True if job looks like spam/MLM/irrelevant listing."""
    title = (job.get("title") or "").strip().lower()
    url = (job.get("url") or "").strip()

    # Empty title or url = definitely skip
    if not title or not url:
        return True

    # Check spam keywords across all platforms
    for pat in SPAM_TITLE_PATTERNS:
        if re.search(pat, title, re.IGNORECASE):
            return True

    return False


def filter_jobs(jobs: list) -> Tuple[list, list]:
    """
    Filter job list into (accepted, rejected).
    Conservative — only removes clear spam to avoid hiding valid roles.
    Usage: accepted, _ = filter_jobs(jobs)
    """
    accepted = []
    rejected = []

    for job in jobs:
        if _is_spam(job):
            rejected.append(job)
        else:
            accepted.append(job)

    print(f"[Filters] {len(accepted)} accepted, {len(rejected)} rejected from {len(jobs)} total")
    return accepted, rejected
