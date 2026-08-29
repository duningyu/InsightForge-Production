from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import QuickStartRequest, SolutionSelectRequest


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v3_golden_cases.json"


def candidate(
    mechanism: str,
    required_data_class: str,
    automation_level: str,
    human_role: str,
    core_decision_logic: str,
    major_dependency: str,
    *,
    title: str | None = None,
    requires_llm_runtime: bool = False,
    requires_rag_runtime: bool = False,
    requires_agent_runtime: bool = False,
):
    from app.schemas import SolutionCandidateDraft

    return SolutionCandidateDraft(
        title=title or mechanism,
        mechanism=mechanism,
        summary=f"{mechanism} summary",
        why_fit="fit",
        user_flow=["输入", "判断", "输出"],
        mvp_pages=["首页"],
        features=["核心功能"],
        inputs=["input"],
        outputs=["output"],
        decision_logic=[core_decision_logic],
        data_requirements=[required_data_class],
        technical_components=[major_dependency],
        implementation_plan=["Week 1", "Week 2"],
        acceptance_cases=["Given X When Y Then Z"],
        risks=["risk"],
        unknowns=["unknown"],
        complexity="low",
        provenance="model_hypothesis",
        required_data_class=required_data_class,
        automation_level=automation_level,
        human_role=human_role,
        core_decision_logic=core_decision_logic,
        major_dependency=major_dependency,
        requires_llm_runtime=requires_llm_runtime,
        requires_rag_runtime=requires_rag_runtime,
        requires_agent_runtime=requires_agent_runtime,
    )


def test_strict_quick_start_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        QuickStartRequest(
            idea="帮便利店减少缺货",
            target_user=None,
            resources=[],
            priority="fast_mvp",
            unexpected="nope",
        )


def test_solution_selection_contract_enforces_strategy_cardinality():
    with pytest.raises(ValidationError):
        SolutionSelectRequest(
            strategy="single",
            candidate_ids=["a", "b"],
            rationale="x",
            human_confirmed=True,
        )
    with pytest.raises(ValidationError):
        SolutionSelectRequest(
            strategy="staged",
            candidate_ids=["a"],
            rationale="x",
            human_confirmed=True,
        )


def test_pairwise_candidates_need_two_material_dimension_differences():
    from app.services.solution_design import validate_solution_set

    candidates = [
        candidate("rule_based", "inventory", "low", "confirm", "threshold", "sqlite"),
        candidate("rule_based", "inventory", "low", "confirm", "threshold", "fastapi"),
    ]
    with pytest.raises(ValueError, match="SOLUTION_DIVERSITY_FAILED"):
        validate_solution_set(candidates, llm_core_required=False)


def test_default_set_requires_non_llm_core_solution():
    from app.services.solution_design import validate_solution_set

    candidates = [
        candidate(
            "assistant", "text", "high", "review", "llm_generation", "openai",
            requires_llm_runtime=True,
        ),
        candidate(
            "search_retrieval", "documents", "medium", "review", "rag_answer", "vector_db",
            requires_llm_runtime=True, requires_rag_runtime=True,
        ),
    ]
    with pytest.raises(ValueError, match="OVERENGINEERED_SOLUTION_SET"):
        validate_solution_set(candidates, llm_core_required=False)


def test_two_materially_different_candidates_are_allowed():
    from app.services.solution_design import validate_solution_set

    candidates = [
        candidate("rule_based", "inventory", "low", "confirm", "threshold", "sqlite"),
        candidate("prediction_based", "sales_history", "medium", "approve", "forecast", "forecast_model"),
    ]
    result = validate_solution_set(candidates, llm_core_required=False)
    assert len(result) == 2


def test_deterministic_runtime_uses_frozen_case_and_preserves_hypothesis_provenance():
    from app.services.ai_runtime import DeterministicDemoRuntime

    runtime = DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    request = QuickStartRequest(
        idea="帮小型便利店减少缺货",
        target_user=None,
        resources=[],
        priority="fast_mvp",
    )
    brief = runtime.interpret_idea(request)
    assert brief.clarification_required is False
    assert brief.provenance["problem"] == "model_hypothesis"
    solutions = runtime.design_solutions(brief)
    assert 2 <= len(solutions.candidates) <= 3
    mechanisms = {item.mechanism for item in solutions.candidates}
    assert "rule_based" in mechanisms
    assert {"prediction_based", "human_in_the_loop"} & mechanisms


def test_deterministic_runtime_marks_ambiguous_school_idea_for_one_clarification():
    from app.services.ai_runtime import DeterministicDemoRuntime

    runtime = DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    brief = runtime.interpret_idea(
        QuickStartRequest(
            idea="帮学生选学校",
            target_user=None,
            resources=[],
            priority="fast_mvp",
        )
    )
    assert brief.clarification_required is True
    assert brief.clarification_question


def test_deterministic_runtime_fails_explicitly_for_unknown_idea():
    from app.services.ai_runtime import DeterministicDemoRuntime, StructuredRuntimeUnavailableError

    runtime = DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    with pytest.raises(StructuredRuntimeUnavailableError, match="DETERMINISTIC_DEMO_UNSUPPORTED"):
        runtime.interpret_idea(
            QuickStartRequest(
                idea="做一个完全未知的火星矿业调度产品",
                target_user=None,
                resources=[],
                priority="fast_mvp",
            )
        )


def test_llm_runtime_request_never_silently_falls_back(monkeypatch):
    from app.services.ai_runtime import StructuredRuntimeUnavailableError, build_structured_runtime

    monkeypatch.setenv("INSIGHTFORGE_STRUCTURED_AI_MODE", "llm_structured")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(StructuredRuntimeUnavailableError, match="OPENAI_API_KEY"):
        build_structured_runtime()


def test_golden_fixture_is_json_and_has_required_cases():
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert {"convenience_replenishment", "school_selection", "two_solution_workflow"} <= set(data)
