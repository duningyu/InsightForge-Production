from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "main.py"


class M4ProviderSearchTripwireTests(unittest.TestCase):
    def test_m4_route_section_is_explicitly_provider_free(self):
        text = MAIN.read_text(encoding="utf-8")
        start = text.index("# M4 internal routes")
        end = text.index('@application.get("/api/audit")', start)
        route_section = text[start:end]
        self.assertIn("M4_PROVIDER_SEARCH_FORBIDDEN", route_section)
        self.assertNotIn("provider_dispatch", route_section)
        self.assertNotIn("search_requests", route_section)

    def test_general_ai_contract_mentions_fake_only(self):
        conditions = (ROOT / "app" / "services" / "if_guide_m4_conditions.py").read_text(encoding="utf-8")
        lifecycle = (ROOT / "app" / "services" / "if_guide_m4.py").read_text(encoding="utf-8")
        self.assertIn('"provider": "fake-provider"', conditions)
        self.assertIn('"provider_allowed": False', conditions)
        self.assertIn('provider_calls: int = 0', lifecycle)
        # Search is not an exposed M4 accounting input; the shared validator
        # still rejects any observed search activity if a fixture supplies it.
        self.assertIn('search_calls = values.pop("search_calls", 0)', conditions)


if __name__ == "__main__":
    unittest.main()
