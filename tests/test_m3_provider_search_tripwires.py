"""Static tripwires for the provider/search-free M3 services and browser path."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
M3_SERVICE_FILES = (
    "action_submission.py",
    "action_review.py",
    "recovery.py",
    "m3_decision.py",
    "if_guide_m3_quality.py",
    "if_guide_m3_inspector.py",
)


def _module_source(name: str) -> str:
    return (ROOT / "app" / "services" / name).read_text(encoding="utf-8")


def test_m3_services_have_no_provider_or_search_runtime_imports():
    forbidden_import_fragments = ("ai_runtime", "provider", "search")
    for name in M3_SERVICE_FILES:
        tree = ast.parse(_module_source(name), filename=name)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not [
            item for item in imports
            if any(fragment in item.lower() for fragment in forbidden_import_fragments)
        ], f"M3 service imports an external runtime: {name}"


def test_browser_harness_has_explicit_external_and_forbidden_action_tripwires():
    source = (ROOT / "tests" / "m3_flow_browser.cjs").read_text(encoding="utf-8")
    for marker in ("external", "generate", "search", "forbidden"):
        assert marker in source
