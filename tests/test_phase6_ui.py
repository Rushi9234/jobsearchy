"""
tests/test_phase6_ui.py — Automated Unit & Integration Tests for Phase 6 UI & Themes
Verifies:
  1. Production Three-Theme System: Classic, Obsidian Dark, Porcelain Light
  2. 1-Click "Demo Profile" Integration (Verified Candidate: Rushikesh Kedar)
  3. Interactive Theme Switcher with localStorage persistence & FOUC prevention
  4. Multi-Page UI Preview Artifacts (preview_ui.html and preview_ui_v2.html)
  5. Live Flask Endpoints serving UI (/) and supporting APIs
"""

import os
import unittest
import json
from web_portal import app


class TestPhase6ThemesAndDesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
        with open(cls.index_path, "r", encoding="utf-8") as f:
            cls.index_html = f.read()

    def test_index_html_exists(self):
        self.assertTrue(os.path.isfile(self.index_path))
        self.assertGreater(len(self.index_html), 1000)

    def test_three_themes_defined(self):
        """Verifies classic, obsidian-dark, and porcelain-light themes are present in CSS."""
        self.assertIn('[data-theme="classic"]', self.index_html)
        self.assertIn('[data-theme="obsidian-dark"]', self.index_html)
        self.assertIn('[data-theme="porcelain-light"]', self.index_html)
        
        # Verify specific theme palette tokens
        self.assertIn('#0c0d14', self.index_html)  # Obsidian dark canvas
        self.assertIn('#1a1b28', self.index_html)  # Obsidian dark card
        self.assertIn('#ebedf5', self.index_html)  # Porcelain light canvas
        self.assertIn('#d5daf0', self.index_html)  # Porcelain light card border

    def test_theme_switcher_controls(self):
        """Verifies ThemeSwitcher component and 3 theme buttons are implemented."""
        self.assertIn('function ThemeSwitcher', self.index_html)
        self.assertIn('Classic', self.index_html)
        self.assertIn('Obsidian', self.index_html)
        self.assertIn('Porcelain', self.index_html)
        self.assertIn('theme-toggle-group', self.index_html)
        self.assertIn('theme-pill', self.index_html)

    def test_theme_persistence_and_anti_fouc(self):
        """Verifies localStorage persistence and early execution script to avoid FOUC."""
        self.assertIn("localStorage.getItem('jobsearchy_theme')", self.index_html)
        self.assertIn("localStorage.setItem('jobsearchy_theme'", self.index_html)
        self.assertIn("document.documentElement.setAttribute('data-theme'", self.index_html)

    def test_card_contrast_and_separation(self):
        """Verifies cards have explicit borders and separation against canvas."""
        self.assertIn('.jc{background:var(--w);', self.index_html)
        self.assertIn('border:1.5px solid var(--g200);', self.index_html)
        self.assertIn('.career-card', self.index_html)
        self.assertIn('.joby-panel', self.index_html)


class TestPhase6DemoProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
        with open(cls.index_path, "r", encoding="utf-8") as f:
            cls.index_html = f.read()

    def test_demo_profile_dataset(self):
        """Verifies realistic verified candidate data is present."""
        self.assertIn('const DEMO_PROFILE', self.index_html)
        self.assertIn('Rushikesh Kedar', self.index_html)
        self.assertIn('SPPU (Pune University)', self.index_html)
        self.assertIn('B.Tech Computer Engineering', self.index_html)
        self.assertIn('8.7', self.index_html)
        self.assertIn('FastAPI', self.index_html)
        self.assertIn('React', self.index_html)
        self.assertIn('Docker', self.index_html)

    def test_demo_profile_button(self):
        """Verifies 1-click Demo Profile button is wired in navigation and resume tab."""
        self.assertIn('btn-demo-profile', self.index_html)
        self.assertIn('⚡ Demo Profile', self.index_html)
        self.assertIn('setProfile(DEMO_PROFILE)', self.index_html)

    def test_no_recruiter_word_in_demo_profile_feature(self):
        """Verifies user mandate: feature must be strictly labeled 'Demo Profile' (no recruiter words in button/label)."""
        # Ensure the button does not say 'Recruiter Profile' or 'Recruiter Mode'
        self.assertNotIn('Recruiter Profile', self.index_html)
        self.assertNotIn('recruiter-profile', self.index_html)
        self.assertNotIn('Recruiter Mode', self.index_html)

    def test_demo_profile_clear_support(self):
        """Verifies user can reset or clear the loaded demo profile in 1 click."""
        self.assertIn("setProfile(null)", self.index_html)


class TestPhase6UIPreviewArtifacts(unittest.TestCase):
    def setUp(self):
        self.static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
        self.preview_v1 = os.path.join(self.static_dir, "preview_ui.html")
        self.preview_v2 = os.path.join(self.static_dir, "preview_ui_v2.html")

    def test_preview_v1_exists_and_valid(self):
        self.assertTrue(os.path.isfile(self.preview_v1))
        with open(self.preview_v1, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("obsidian-dark", content)
        self.assertIn("porcelain-light", content)

    def test_preview_v2_exists_and_contains_all_pages(self):
        self.assertTrue(os.path.isfile(self.preview_v2))
        with open(self.preview_v2, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("<!DOCTYPE html>", content)
        # Check all 4 multi-page panel views are defined
        self.assertIn('id="panelDash"', content)
        self.assertIn('id="panelResume"', content)
        self.assertIn('id="panelSaved"', content)
        self.assertIn('id="panelGaps"', content)
        # Check theme palettes
        self.assertIn("obsidian-dark", content)
        self.assertIn("porcelain-light", content)


class TestPhase6LiveEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_frontend_root_served(self):
        """Verifies GET / serves index.html with HTTP 200."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/html', res.content_type)
        html = res.data.decode('utf-8')
        res.close()
        self.assertIn('JobSearchy', html)
        self.assertIn('DEMO_PROFILE', html)
        self.assertIn('ThemeSwitcher', html)

    def test_jobs_api_available(self):
        """Verifies /api/jobs responds properly for frontend queries."""
        res = self.client.get('/api/jobs?limit=5')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIsInstance(data, list)
        if data:
            self.assertIn('title', data[0])
            self.assertIn('company', data[0])

    def test_career_gps_endpoint(self):
        """Verifies /api/career-gps evaluates career path readiness."""
        res = self.client.get('/api/career-gps')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('readiness_score', data)
        self.assertIn('role_paths', data)

    def test_joby_chat_endpoint(self):
        """Verifies /api/joby-chat assists candidates contextually."""
        res = self.client.post('/api/joby-chat',
                               data=json.dumps({"message": "How do I raise my match score for ML roles?", "profile": {"name": "Rushikesh"}}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('reply', data)
        self.assertGreater(len(data['reply']), 10)


if __name__ == '__main__':
    unittest.main()
