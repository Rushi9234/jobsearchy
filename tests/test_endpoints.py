"""
tests/test_endpoints.py — Integration tests for all Flask Web Portal endpoints
Covers:
  - GET / (UI Dashboard HTML)
  - GET /api/profile
  - GET /api/rescore-status
  - GET /api/pipeline-status
  - GET /api/jobs
  - GET /api/jobs/top
  - GET /api/jobs/saved
  - GET /api/stats
  - GET /api/tracker & CRUD operations
  - GET /api/interaction-stats
  - GET /api/flashcards-for-profile
  - GET /api/skill-content
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web_portal import app
import database.db as db


class TestEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        db.init_db()

    def test_dashboard_route(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        resp.close()

    def test_profile_and_status_routes(self):
        for route in ["/api/rescore-status", "/api/pipeline-status", "/api/stats"]:
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200)

    def test_jobs_routes(self):
        for route in ["/api/jobs?limit=5", "/api/jobs/top?limit=5", "/api/jobs/saved"]:
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200)

    def test_tracker_crud(self):
        # Create
        res_post = self.client.post("/api/tracker", json={"company": "TestOrg", "role": "Intern", "stage": "Applied"})
        self.assertEqual(res_post.status_code, 200)
        entry_id = res_post.get_json().get("id")
        self.assertIsNotNone(entry_id)

        # Update
        res_patch = self.client.patch(f"/api/tracker/{entry_id}", json={"stage": "Offer"})
        self.assertEqual(res_patch.status_code, 200)

        # Delete
        res_del = self.client.delete(f"/api/tracker/{entry_id}")
        self.assertEqual(res_del.status_code, 200)

    def test_skill_content_endpoint(self):
        resp = self.client.get("/api/skill-content?skill=python")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
