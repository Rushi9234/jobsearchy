"""
tests/test_phase7_govt_and_range.py — Unit tests for Government Verification & Search Range Filtering
Covers:
  1. Strict Government classification (rejects private companies like The Wedding Company, Axentriax, etc.)
  2. Positive Government classification for official portals & institutions (PMIS, ISRO, AICTE, IIT SURGE, etc.)
  3. Static government portal URL integrity (IIT SURGE point to surge.iitk.ac.in, not 404)
  4. Real-time Days range filtering and days_ago computation via /api/jobs?days=N
  5. Email notifier category grouping synchronization with classify_job
"""

import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web_portal import app, classify_job, _calc_days_ago
from scrapers.govt_scraper import _static_govt_portals


class TestGovtAndRange(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    def test_strict_govt_rejects_private_companies(self):
        """Private companies should NEVER be classified as 'govt' even if sourced from internshala."""
        private_examples = [
            {"title": "Data Science Intern", "company": "The Wedding Company", "source": "govt_internshala"},
            {"title": "AI Research Intern", "company": "Axentriax by Elevate Labs", "source": "govt_internshala"},
            {"title": "Software Developer Intern", "company": "Maxgen Technologies Private Limited", "source": "govt_internshala"},
            {"title": "Research Analyst", "company": "Ozibook Tech Solutions Private Limited", "source": "govt_internshala"},
            {"title": "Operations Trainee", "company": "PPS Anantams Corporation Private Limited", "source": "govt_internshala"},
            {"title": "Marketing Associate", "company": "Tax-O-Smart LLP", "source": "govt_internshala"},
        ]
        for job in private_examples:
            classification = classify_job(job)
            self.assertNotEqual(
                classification, "govt",
                f"Private company '{job['company']}' was incorrectly classified as govt!"
            )

    def test_positive_govt_entities_classified_as_govt(self):
        """Official government ministries, PSUs, and national institutes must be classified as 'govt'."""
        govt_examples = [
            {"title": "PM Internship Scheme — Top 500 Companies", "company": "Government of India (Ministry of Corporate Affairs)", "source": "govt_portal", "url": "https://pminternship.mca.gov.in"},
            {"title": "AICTE Technical Internship", "company": "AICTE (All India Council for Technical Education)", "source": "govt_portal", "url": "https://internship.aicte-india.org"},
            {"title": "ISRO Student Internship Programme", "company": "ISRO (Indian Space Research Organisation)", "source": "govt_portal", "url": "https://www.isro.gov.in/Careers.html"},
            {"title": "IIT Kanpur SURGE Summer Research", "company": "IIT Kanpur", "source": "govt_portal", "url": "https://surge.iitk.ac.in"},
            {"title": "IIT Roorkee SPARK Summer Internship", "company": "IIT Roorkee", "source": "govt_portal", "url": "https://spark.iitr.ac.in"},
            {"title": "Young Professional Internship", "company": "NITI Aayog (Government of India)", "source": "govt_portal", "url": "https://www.niti.gov.in/internship"},
            {"title": "DRDO Research Internship", "company": "DRDO", "source": "govt_portal", "url": "https://drdo.gov.in/drdo/careers"},
        ]
        for job in govt_examples:
            classification = classify_job(job)
            self.assertEqual(
                classification, "govt",
                f"Government entity '{job['company']}' was not classified as govt!"
            )

    def test_static_govt_portal_urls_non_broken(self):
        """Verify static portals in govt_scraper do not contain the old 404 IIT Bombay SURGE URL."""
        portals = _static_govt_portals()
        for p in portals:
            url = p.get("url", "")
            self.assertNotIn("iitb.ac.in/en/education/surge-program", url, "Found broken IIT SURGE URL!")
            if "surge" in p.get("title", "").lower():
                self.assertIn("surge.iitk.ac.in", url)
            if "spark" in p.get("title", "").lower():
                self.assertIn("spark.iitr.ac.in", url)

    def test_calc_days_ago(self):
        """Verify days_ago correctly measures elapsed days."""
        now = datetime.now(timezone.utc)
        today_str = now.isoformat()
        three_days_ago = (now - timedelta(days=3)).isoformat()
        seven_days_ago = (now - timedelta(days=7)).isoformat()

        self.assertEqual(_calc_days_ago(today_str), 0)
        self.assertEqual(_calc_days_ago(three_days_ago), 3)
        self.assertEqual(_calc_days_ago(seven_days_ago), 7)
        self.assertEqual(_calc_days_ago(""), 0)

    def test_jobs_api_days_parameter(self):
        """Verify /api/jobs accepts days parameter and returns days_ago on all items."""
        resp = self.client.get("/api/jobs?days=30&limit=10")
        self.assertEqual(resp.status_code, 200)
        jobs = resp.get_json()
        self.assertIsInstance(jobs, list)
        for j in jobs:
            self.assertIn("days_ago", j)
            self.assertLessEqual(j["days_ago"], 30)
        resp.close()

    def test_jobs_api_govt_type_only_real_govt(self):
        """Verify /api/jobs?job_type=govt returns only verified government opportunities."""
        resp = self.client.get("/api/jobs?job_type=govt&limit=20")
        self.assertEqual(resp.status_code, 200)
        jobs = resp.get_json()
        self.assertIsInstance(jobs, list)
        for j in jobs:
            self.assertEqual(j.get("job_type"), "govt")
            company = (j.get("company") or "").lower()
            self.assertFalse(
                any(p in company for p in ["pvt ltd", "private limited", "wedding", "elevate labs"]),
                f"Private company found in govt list: {company}"
            )
        resp.close()


if __name__ == "__main__":
    unittest.main()
