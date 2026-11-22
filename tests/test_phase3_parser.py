"""
tests/test_phase3_parser.py — Unit tests for Phase 3 Resume Parser
Covers:
  - extract_name headline rejection ('Full Stack Developer', 'Software Engineer')
  - extract_name support for initials ('R. K. Sharma')
  - extract_college without student summary false positives
  - extract_current_course word boundaries (no 'Bear' market matches)
  - extract_education pairing
  - Real resumes test (Rushikesh_Kedar_Resume.pdf, Akash_Bhuyan_Resume_1_1.pdf)
  - parse_resume_hybrid fallback contract
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.resume_parser import (
    extract_name,
    extract_college,
    extract_current_course,
    extract_education,
    parse_resume,
)
from utils.resume_llm_parser import parse_resume_hybrid


class TestPhase3Parser(unittest.TestCase):

    def test_name_headline_rejection(self):
        mock_text = """
Full Stack Developer
Rushikesh Baban Kedar
rushikedar40@gmail.com | +91 8605453442
"""
        name = extract_name(mock_text)
        self.assertEqual(name, "Rushikesh Baban Kedar")

    def test_name_initials_support(self):
        mock_text = """
CURRICULUM VITAE
Artificial Intelligence Enthusiast
R. K. Sharma
rksharma@example.com | 9876543210
"""
        name = extract_name(mock_text)
        self.assertEqual(name, "R. K. Sharma")

    def test_college_no_summary_false_positive(self):
        mock_text = """
Rushikesh Baban Kedar
Summary
Computer Engineering student with hands-on experience in backend development, REST APIs, full-stack web
Education
MIT Academy of Engineering, Pune 2023 - 2027
B.Tech in Computer Science Engineering CGPA: 7.43/10
"""
        college = extract_college(mock_text)
        self.assertEqual(college, "MIT Academy of Engineering, Pune")

    def test_course_word_boundary_no_bear(self):
        mock_text = """
Projects
InvestEdge Platform: Market Regimes: Bear/Sideways/High Volatility
Education
Bachelor of Engineering (Computer Science)
MIT Academy of Engineering - Pune
"""
        course = extract_current_course(mock_text)
        self.assertEqual(course, "Bachelor of Engineering (Computer Science)")

    def test_education_pairing(self):
        mock_text = """
Education
Air Force School Viman Nagar - Pune
Higher Secondary Education
MIT Academy of Engineering - Pune
Bachelor of Engineering (Computer Science)
"""
        edu = extract_education(mock_text)
        self.assertGreaterEqual(len(edu), 2)
        insts = [e["institution"] for e in edu]
        self.assertTrue(any("MIT Academy" in inst for inst in insts))
        self.assertTrue(any("Air Force School" in inst for inst in insts))

    def test_real_resume_rushi(self):
        rushi_pdf = ROOT / "uploads" / "Rushikesh_Kedar_Resume.pdf"
        if rushi_pdf.exists():
            p = parse_resume(str(rushi_pdf))
            self.assertEqual(p["name"], "Rushikesh Baban Kedar")
            self.assertEqual(p["college"], "MIT Academy of Engineering, Pune")
            self.assertIn("Computer Science", p["current_course"])
            self.assertIn("python", p["skills"])

    def test_real_resume_akash(self):
        akash_pdf = ROOT / "uploads" / "Akash_Bhuyan_Resume_1_1.pdf"
        if akash_pdf.exists():
            p = parse_resume(str(akash_pdf))
            self.assertEqual(p["name"], "Akash Bhuyan")
            self.assertEqual(p["college"], "MIT Academy of Engineering - Pune")
            self.assertIn("Engineering", p["current_course"])
            self.assertIn("python", p["skills"])

    def test_hybrid_fallback_contract(self):
        rushi_pdf = ROOT / "uploads" / "Rushikesh_Kedar_Resume.pdf"
        if rushi_pdf.exists():
            p = parse_resume_hybrid(str(rushi_pdf))
            self.assertIn("name", p)
            self.assertIn("skills", p)
            self.assertIn("skills_weighted", p)
            self.assertIn("college", p)
            self.assertEqual(p["name"], "Rushikesh Baban Kedar")


if __name__ == "__main__":
    unittest.main()
