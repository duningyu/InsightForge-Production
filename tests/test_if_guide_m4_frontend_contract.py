from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "app" / "static" / "index.html"
JS = ROOT / "app" / "static" / "app.js"


class M4FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")

    def test_m4_panel_is_explicitly_read_only_and_manual(self):
        self.assertIn('id="m4-evaluation-panel"', self.html)
        self.assertIn('id="m4-refresh"', self.html)
        self.assertIn('id="m4-report-export"', self.html)
        self.assertIn("M4 控制评测", self.html)
        self.assertIn("M4_READ_ONLY", self.html)
        self.assertIn("loadM4Report", self.js)
        self.assertIn("X-InsightForge-Internal", self.js)

    def test_project_load_does_not_auto_start_m4(self):
        self.assertIn("m4", self.js)
        self.assertNotIn("POST /api/internal/m4", self.js)
        self.assertNotIn("fetch('/api/internal/m4", self.js)

    def test_frontend_does_not_render_private_content(self):
        # The existing project UI may legitimately handle product input fields;
        # this contract applies only to the new M4 read-only panel/functions.
        start = self.js.index("function m4Headers()")
        end = self.js.index("async function loadM3State()", start)
        m4_code = self.js[start:end]
        for field in ("raw_idea", "raw_transcript", "private_artifact_body"):
            self.assertNotIn(field, m4_code)


if __name__ == "__main__":
    unittest.main()
