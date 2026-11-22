"""
tests/test_phase4_scrapers.py — Unit tests for Phase 4 Scraper Fleet Modernization
Covers:
  - PMIS Government Scraper structure, stipends, and scheme roles
  - Open Jobs Developer API Scraper (Jobicy + Arbeitnow)
  - Inactive scraper preservation (Wellfound & Naukri return empty lists cleanly)
  - Scheduler dynamic path resolution
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.pmis_scraper import scrape_pmis_jobs
from scrapers.open_jobs_scraper import scrape_open_jobs, scrape_jobicy, scrape_arbeitnow
import scrapers.wellfound_scraper as wellfound
import scrapers.naukri_scraper as naukri
from scheduler import get_searchy_root


class TestPhase4Scrapers(unittest.TestCase):

    def test_pmis_scraper_structure(self):
        jobs = scrape_pmis_jobs()
        self.assertGreaterEqual(len(jobs), 5)
        for j in jobs:
            self.assertTrue(len(j["stipend"]) > 0)
            self.assertIn("government", j["tags"])
        self.assertTrue(any("5,000" in j["stipend"] for j in jobs))

    def test_open_jobs_scraper_schema(self):
        jobs = scrape_open_jobs(keywords=["python", "data"], limit=6)
        self.assertIsInstance(jobs, list)
        for j in jobs:
            self.assertIn("job_id", j)
            self.assertIn("title", j)
            self.assertIn("company", j)
            self.assertIn("url", j)
            self.assertIn("scraped_at", j)

    def test_inactive_scrapers_safe(self):
        self.assertEqual(wellfound.scrape(), [])
        self.assertEqual(naukri.scrape(), [])
        self.assertFalse(wellfound.ENABLED)
        self.assertFalse(naukri.ENABLED)

    def test_scheduler_path_resolution(self):
        root = get_searchy_root()
        self.assertTrue(Path(root).exists())
        self.assertTrue((Path(root) / "web_portal.py").exists())


if __name__ == "__main__":
    unittest.main()
