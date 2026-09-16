from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "main.py"
SCHEMAS = ROOT / "app" / "schemas.py"


class M4RouteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_text = MAIN.read_text(encoding="utf-8")
        cls.schema_text = SCHEMAS.read_text(encoding="utf-8")
        cls.main_tree = ast.parse(cls.main_text)

    def test_m4_services_are_wired_into_app_state(self):
        for name in (
            "M4EvaluationService",
            "M4AssignmentService",
            "M4GoldSetService",
            "M4QualityService",
            "M4ReportingService",
            "M4InspectorService",
        ):
            self.assertIn(name, self.main_text)
        for name in (
            "m4_evaluation",
            "m4_assignment",
            "m4_gold_set",
            "m4_quality",
            "m4_reporting",
            "m4_inspector",
        ):
            self.assertIn(f"application.state.{name}", self.main_text)

    def test_m4_internal_routes_exist_and_public_m4_routes_do_not(self):
        expected = (
            "/api/internal/m4/experiments",
            "/api/internal/m4/experiments/{experiment_id}/freeze",
            "/api/internal/m4/experiments/{experiment_id}/participants",
            "/api/internal/m4/experiments/{experiment_id}/sessions",
            "/api/internal/m4/sessions/{session_id}/gold-set",
            "/api/internal/m4/sessions/{session_id}/quality",
            "/api/internal/m4/experiments/{experiment_id}/report",
        )
        for route in expected:
            self.assertIn(route, self.main_text)
        decorators = [
            node.decorator_list
            for node in ast.walk(self.main_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        route_literals = []
        for decorator_list in decorators:
            for decorator in decorator_list:
                if isinstance(decorator, ast.Call) and decorator.args:
                    first = decorator.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        route_literals.append(first.value)
        self.assertFalse(any(route.startswith("/api/m4") for route in route_literals))

    def test_internal_actor_is_not_client_selectable(self):
        self.assertIn("X-InsightForge-Internal", self.main_text)
        self.assertIn("X-Actor", self.main_text)
        for field in ("actor_id", "database_path", "workspace"):
            self.assertNotIn(f"{field}: str", self.schema_text)

    def test_m4_request_models_are_strict(self):
        for name in (
            "M4CreateExperimentRequest",
            "M4UpdateExperimentRequest",
            "M4CreateParticipantRequest",
            "M4AssignSessionRequest",
            "M4TransitionSessionRequest",
            "M4OperationalAccountingRequest",
            "M4GoldSetRequest",
            "M4AnnotationRequest",
            "M4QualityRequest",
            "M4FinalizeSessionRequest",
        ):
            self.assertIn(f"class {name}(StrictModel)", self.schema_text)


if __name__ == "__main__":
    unittest.main()
