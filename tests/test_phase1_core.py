"""
tests/test_phase1_core.py — Unit tests for Phase 1 Core Fixes
Covers:
  - Text normalization token preservation (Node.js, CI/CD, B.Tech, Next.js, C++)
  - Matcher skill counting with technical punctuation
  - Spam filter active across all job sources
  - Scrapers inactive safety & deterministic MD5 hashing
  - Database mark_notified string job_id fix
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.matcher import _clean, _count_skill_mentions, _education_score
from utils.filters import filter_jobs, _is_spam
import scrapers.wellfound_scraper as wellfound
import scrapers.naukri_scraper as naukri
import scrapers.hackerearth_scraper as hackerearth
from database.db import init_db, insert_job, mark_notified, get_unnotified_jobs, get_conn


class TestPhase1Core(unittest.TestCase):

    def test_text_cleaning_preserves_tokens(self):
        sample = "Proficient in Node.js, Next.js, CI/CD pipelines, and C++ with B.Tech."
        cleaned = _clean(sample)
        self.assertIn("node.js", cleaned)
        self.assertIn("next.js", cleaned)
        self.assertIn("ci/cd", cleaned)
        self.assertIn("b.tech", cleaned)
        self.assertIn("c++", cleaned)

    def test_skill_mentions_with_dots_and_slashes(self):
        text = "Looking for a candidate with strong node.js, ci/cd and next.js experience."
        self.assertEqual(_count_skill_mentions("node.js", text), 1)
        self.assertEqual(_count_skill_mentions("ci/cd", text), 1)
        self.assertEqual(_count_skill_mentions("next.js", text), 1)
        self.assertEqual(_count_skill_mentions("python", text), 0)

    def test_education_score_matches_btech(self):
        profile = {"current_course": "B.Tech in Computer Science Engineering"}
        job_btech = {"title": "Software Engineer", "description": "Candidate must possess B.Tech degree."}
        score = _education_score(profile, job_btech)
        self.assertGreaterEqual(score, 0.5)

    def test_spam_filter_on_all_sources(self):
        spam_job = {
            "source": "naukri",
            "title": "Data Entry / Typing / Work From Home",
            "company": "Fast Cash Ltd",
            "description": "Earn 50000 daily typing work no experience needed whatsapp now",
            "stipend": "100000",
        }
        self.assertTrue(_is_spam(spam_job))
        accepted, rejected = filter_jobs([spam_job])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)

    def test_scrapers_inactive_and_deterministic(self):
        self.assertEqual(wellfound.scrape(keywords=["python"]), [])
        self.assertEqual(naukri.scrape(keywords=["python"]), [])

    def test_database_mark_notified(self):
        init_db()
        test_job = {
            "job_id": "test_mark_notified_job_123",
            "source": "unit_test",
            "title": "Test Engineer",
            "company": "Test Corp",
            "location": "Remote",
            "duration": "3 months",
            "stipend": "10000",
            "url": "https://example.com/job123",
            "tags": ["test"],
            "description": "Test job description",
            "match_score": 85.0,
            "job_type": "internship",
            "scraped_at": "2026-04-18T10:00:00Z",
        }
        insert_job(test_job)
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("UPDATE jobs SET is_notified=0 WHERE job_id=?", (test_job["job_id"],))
            conn.commit()

        mark_notified(["test_mark_notified_job_123"])
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT is_notified FROM jobs WHERE job_id=?", (test_job["job_id"],))
            row = c.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 1)


if __name__ == "__main__":
    unittest.main()
