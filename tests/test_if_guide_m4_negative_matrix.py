from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "main.py"
REPORTING = ROOT / "app" / "services" / "if_guide_m4_reporting.py"


class M4NegativeMatrixTests(unittest.TestCase):
    def test_internal_routes_require_internal_headers(self):
        text = MAIN.read_text(encoding="utf-8")
        self.assertIn("M4_INTERNAL_ACCESS_REQUIRED", text)
        self.assertIn("X-InsightForge-Internal", text)

    def test_report_and_inspector_exclude_private_bodies(self):
        text = REPORTING.read_text(encoding="utf-8")
        for key in ("raw_idea", "raw_transcript", "private_artifact_body", "credentials"):
            self.assertIn(key, text)

    def test_m4_route_block_does_not_use_direct_sql(self):
        text = MAIN.read_text(encoding="utf-8")
        marker = "# M4 internal"
        if marker in text:
            route_block = text[text.index(marker):]
            self.assertNotIn("INSERT INTO", route_block)
            self.assertNotIn("UPDATE ", route_block)
            self.assertNotIn("DELETE FROM", route_block)


if __name__ == "__main__":
    unittest.main()
