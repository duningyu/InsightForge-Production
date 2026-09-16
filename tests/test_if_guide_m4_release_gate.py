from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORTING = (ROOT / "app/services/if_guide_m4_reporting.py").read_text(encoding="utf-8")


class M4ReleaseGateContractTests(unittest.TestCase):
    def test_report_exposes_release_gate_without_claiming_release(self):
        self.assertIn("release_gate", REPORTING)
        self.assertIn("hard_gate_violations", REPORTING)
        self.assertIn("RELEASE_NOT_AUTHORIZED", REPORTING)
        self.assertIn("build_release_gate_report", REPORTING)

    def test_release_gate_is_descriptive_and_safe(self):
        self.assertIn("DESCRIPTIVE_ONLY", REPORTING)
        self.assertIn("automatic_release", REPORTING)
        self.assertIn("safe_only", REPORTING)


if __name__ == "__main__":
    unittest.main()
