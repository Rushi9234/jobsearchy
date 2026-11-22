"""
tests/test_phase2_backend.py — Unit tests for Phase 2 Backend Fixes
Covers:
  - Resend HTTPS REST API config & fallback variable names
  - SQLite & Turso database connectivity
  - Email HTML escaping against script injection
  - Email digest error handling
  - POST /api/send-digest HTTP 200 response
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database.db as db
from notifiers.email_notifier import _get_config, _job_card, send_daily_digest
from web_portal import app


class TestPhase2Backend(unittest.TestCase):

    def test_config_fallback_variable_names(self):
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key_123"}, clear=False):
            cfg = _get_config()
            self.assertEqual(cfg["resend_api_key"], "re_test_key_123")

    def test_database_connection_and_queries(self):
        db.init_db()
        stats = db.get_stats()
        self.assertIsInstance(stats, dict)
        self.assertIn("total_jobs", stats)

    def test_job_card_html_sanitization(self):
        malicious_job = {
            "title": "<script>alert('xss')</script> Backend Developer",
            "company": "SafeCorp & Co <img src=x onerror=alert(1)>",
            "match_score": 92.5,
            "location": "Remote",
            "stipend": "₹25,000",
            "duration": "6 months",
            "url": "https://example.com/apply?id=1&name=test",
            "description": "Building APIs <script>bad()</script>",
            "tags": ["python", "<tag>"],
        }
        card_html = _job_card(malicious_job)
        self.assertNotIn("<script>", card_html)
        self.assertNotIn("<img src=x", card_html)
        self.assertIn("&lt;script&gt;", card_html)

    def test_send_daily_digest_empty_jobs(self):
        success = send_daily_digest(jobs=[], recipient_email="test@example.com")
        self.assertTrue(success)

    def test_send_digest_endpoint_success(self):
        client = app.test_client()
        with patch("web_portal.send_daily_digest", return_value=True):
            resp = client.post("/api/send-digest", json={"email": "tester@example.com"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))


if __name__ == "__main__":
    unittest.main()
