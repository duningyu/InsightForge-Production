"""Complete synthetic output for transport/lifecycle tests; no provider I/O."""
from pathlib import Path

from app.schemas import QuickStartRequest
from app.services.ai_runtime import DeterministicDemoRuntime


def complete_solution_payload():
    runtime = DeterministicDemoRuntime(fixture_path=Path(__file__).parent / "fixtures" / "v3_golden_cases.json")
    brief = runtime.interpret_idea(QuickStartRequest(idea="帮小型便利店减少缺货"))
    return {"candidates": [{**candidate.model_dump(), "id": f"synthetic-{index}"}
                           for index, candidate in enumerate(runtime.design_solutions(brief).candidates)]}
