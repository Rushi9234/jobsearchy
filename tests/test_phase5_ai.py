"""
tests/test_phase5_ai.py — Automated Unit & Integration Tests for Phase 5
Verifies:
  1. Dynamic Career GPS Engine (role paths, readiness %, live skill gaps, 7-day action plan)
  2. Joby AI Career Copilot (Groq -> Gemini -> Smart Contextual Fallback)
  3. Live Flask Endpoints (/api/career-gps, /api/joby-chat)
"""

import unittest
import json
from utils.career_gps import evaluate_career_gps, _normalize_skill
from utils.joby_copilot import generate_joby_reply, _smart_offline_reply
from web_portal import app


class TestCareerGPS(unittest.TestCase):
    def setUp(self):
        self.sample_profile = {
            "name": "Rushikesh Kedar",
            "college": "MIT Academy of Engineering, Pune",
            "current_course": "B.Tech in Computer Science Engineering",
            "skills": [
                "python", "sql", "pandas", "numpy", "matplotlib",
                "machine learning", "scikit-learn", "fastapi", "git"
            ]
        }
        self.sample_jobs = [
            {
                "id": 1,
                "title": "Data Analyst Intern",
                "company": "Tata Analytics",
                "match_score": 88.0,
                "tags": json.dumps(["python", "sql", "power bi", "docker", "excel"])
            },
            {
                "id": 2,
                "title": "Machine Learning Engineer",
                "company": "Reliance AI Labs",
                "match_score": 82.0,
                "tags": json.dumps(["python", "pytorch", "deep learning", "docker"])
            }
        ]

    def test_normalize_skill(self):
        self.assertEqual(_normalize_skill("  ReactJS  "), "react")
        self.assertEqual(_normalize_skill("JS"), "javascript")
        self.assertEqual(_normalize_skill("K8s"), "kubernetes")
        self.assertEqual(_normalize_skill("CI CD"), "ci/cd")

    def test_evaluate_career_gps_with_profile(self):
        gps = evaluate_career_gps(profile=self.sample_profile, jobs=self.sample_jobs)
        self.assertIn("recommended_role", gps)
        self.assertIn("readiness_score", gps)
        self.assertGreaterEqual(gps["readiness_score"], 60)
        self.assertEqual(gps["candidate_name"], "Rushikesh Kedar")
        self.assertTrue(len(gps["role_paths"]) >= 4)
        # Check role sorting
        scores = [r["score"] for r in gps["role_paths"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_evaluate_career_gps_empty_profile(self):
        gps = evaluate_career_gps(profile={}, jobs=[])
        self.assertIn("recommended_role", gps)
        self.assertIn("action_plan", gps)
        self.assertEqual(len(gps["action_plan"]), 7)
        self.assertFalse(gps["has_profile"])
        self.assertGreaterEqual(gps["readiness_score"], 35)

    def test_skill_gaps_extraction_from_jobs(self):
        gps = evaluate_career_gps(profile=self.sample_profile, jobs=self.sample_jobs)
        gaps = gps.get("skill_gaps", [])
        self.assertTrue(len(gaps) >= 2)
        gap_names = [g["name"].lower() for g in gaps]
        # Docker and Power BI were in job tags and not in sample profile skills
        self.assertTrue(any("docker" in g for g in gap_names) or any("power bi" in g for g in gap_names))

    def test_action_plan_contains_7_days(self):
        gps = evaluate_career_gps(profile=self.sample_profile, jobs=self.sample_jobs)
        plan = gps["action_plan"]
        self.assertEqual(len(plan), 7)
        self.assertTrue(plan[0].startswith("Day 1:"))
        self.assertTrue(plan[6].startswith("Day 7:"))


class TestJobyCopilot(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "name": "Akash Bhuyan",
            "college": "MIT Academy of Engineering - Pune",
            "current_course": "Bachelor of Engineering (Computer Science)",
            "skills": ["python", "react", "fastapi", "machine learning", "docker", "git"]
        }
        self.top_jobs = [
            {
                "title": "Full Stack Intern",
                "company": "Infosys",
                "match_score": 87.5,
                "url": "https://example.com/job/1"
            }
        ]
        self.career_gps = {
            "recommended_role": "Full Stack / Python Developer Intern",
            "readiness_score": 84,
            "skill_gaps": [
                {"name": "Kubernetes", "priority": "High"},
                {"name": "AWS Deployment", "priority": "High"}
            ]
        }

    def test_analyze_resume_offline(self):
        reply = _smart_offline_reply("Analyze Resume", self.profile, self.top_jobs, self.career_gps)
        self.assertIn("Akash", reply)
        self.assertIn("technical skills", reply.lower())
        self.assertIn("ats optimization", reply.lower())

    def test_find_matching_jobs_offline(self):
        reply = _smart_offline_reply("Find Matching Jobs", self.profile, self.top_jobs, self.career_gps)
        self.assertIn("Infosys", reply)
        self.assertIn("Full Stack Intern", reply)

    def test_show_skill_gaps_offline(self):
        reply = _smart_offline_reply("Show Skill Gaps", self.profile, self.top_jobs, self.career_gps)
        self.assertIn("Kubernetes", reply)

    def test_pmis_guidance(self):
        reply = _smart_offline_reply("Tell me about PMIS government stipend", self.profile, self.top_jobs, self.career_gps)
        self.assertIn("5,000", reply)
        self.assertIn("pminternship.mca.gov.in", reply)

    def test_generate_joby_reply_contract(self):
        res = generate_joby_reply(
            message="What should I prepare for interview?",
            history=[],
            profile=self.profile,
            top_jobs=self.top_jobs,
            career_gps=self.career_gps
        )
        self.assertIn("reply", res)
        self.assertIn("model", res)
        self.assertEqual(res["status"], "success")
        self.assertTrue(len(res["reply"]) > 20)


class TestPhase5Endpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_get_career_gps_endpoint(self):
        resp = self.client.get("/api/career-gps")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("recommended_role", data)
        self.assertIn("readiness_score", data)
        self.assertIn("role_paths", data)
        self.assertIn("skill_gaps", data)
        self.assertIn("action_plan", data)
        self.assertIn("metrics", data)

    def test_joby_chat_endpoint_success(self):
        resp = self.client.post(
            "/api/joby-chat",
            json={"message": "Analyze Resume", "history": []}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("reply", data)
        self.assertTrue(len(data["reply"]) > 10)

    def test_joby_chat_endpoint_empty_message(self):
        resp = self.client.post("/api/joby-chat", json={"message": ""})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
