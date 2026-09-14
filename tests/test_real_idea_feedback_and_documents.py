import json

import pytest

from app.schemas import SolutionSetDraft
from app.services.real_idea_evaluation import RealIdeaEvaluationService


class FakeSolutionsRuntime:
    provider = "isolated_fake"
    model = "fake-solutions"
    prompt_version = "test"
    schema_version = "test"
    mode = "fake"

    def __init__(self, result_count=3):
        self.result_count = result_count
        self.provider_transport_attempts = 1

    def design_solutions(self, _brief, **_kwargs):
        candidate = {
            "title": "Focused workflow",
            "mechanism": "workflow_based",
            "summary": "A concise workflow for the core user need.",
            "why_fit": "It keeps the main task easy to complete.",
            "user_flow": ["capture", "review"],
            "mvp_pages": ["home"],
            "features": ["capture"],
            "inputs": ["user input"],
            "outputs": ["clear next step"],
            "decision_logic": ["show the next step"],
            "data_requirements": ["user-provided data"],
            "technical_components": ["web application"],
            "implementation_plan": ["build the core flow"],
            "acceptance_cases": ["user completes the flow"],
            "risks": ["adoption"],
            "unknowns": ["retention"],
            "complexity": "low",
            "provenance": "model_hypothesis",
            "required_data_class": "user input",
            "automation_level": "low",
            "human_role": "user decides",
            "core_decision_logic": "keep the core flow explicit",
            "major_dependency": "none",
        }
        candidates = []
        for i in range(self.result_count):
            candidates.append({
                **candidate,
                "title": f"Focused workflow {i}",
                "mechanism": ["workflow_based", "human_in_the_loop", "automation"][i % 3],
                "summary": f"A concise workflow variation {i} for the core user need.",
                "user_flow": ["capture", "review", f"step-{i}"],
                "mvp_pages": ["home", f"page-{i}"],
                "requires_llm_runtime": i == 2,
            })
        return SolutionSetDraft(
            candidates=candidates,
            llm_core_required=False,
        )


def _confirmed_brief(db, project_id):
    db.execute(
        """
        INSERT INTO idea_briefs(
            id, project_id, version, original_idea, target_user, problem, desired_outcome,
            known_resources_json, constraints_json, unknowns_json, provenance_json,
            confirmation_status, created_at
        ) VALUES (?, ?, 1, ?, ?, ?, ?, '[]', '[]', '[]', ?, 'confirmed', ?)
        """,
        (
            "brief-real-idea-test",
            project_id,
            "A focused user idea",
            "people with the problem",
            "the current problem",
            "a useful outcome",
            json.dumps({}, ensure_ascii=False),
            "2026-09-15T00:00:00+00:00",
        ),
    )


@pytest.fixture
def real_idea_sample(db):
    service = RealIdeaEvaluationService(db, durable_budget=6)
    service.start_batch("batch-feedback-test")
    sample = service.start_sample("batch-feedback-test", "same isolated raw idea")
    _confirmed_brief(db, sample.project_id)
    service.transition_sample(
        sample.sample_id,
        from_state="QUICKSTART_PENDING",
        to_state="AWAITING_BRIEF_REVIEW",
    )
    return db, service, sample


def test_solutions_review_requires_three_persisted_candidates(real_idea_sample):
    _db, service, sample = real_idea_sample
    result = service.run_solutions(
        sample.sample_id,
        runtime=FakeSolutionsRuntime(result_count=3),
    )
    assert result.solution_count == 3
    assert result.transport_count == 1
    assert result.status == "AWAITING_SOLUTION_REVIEW"


def test_selection_is_user_bound_and_provider_free(real_idea_sample):
    _db, service, sample = real_idea_sample
    service.run_solutions(sample.sample_id, runtime=FakeSolutionsRuntime())
    result = service.record_selection(
        sample.sample_id,
        selected_ordinal=2,
        reason="Fits the main workflow.",
    )
    assert result.provider_transport_count == 0
    assert result.selected_solution_ordinal == 2


def test_selection_reason_is_limited_to_one_to_three_sentences(real_idea_sample):
    _db, service, sample = real_idea_sample
    service.run_solutions(sample.sample_id, runtime=FakeSolutionsRuntime())
    with pytest.raises(ValueError, match="1 to 3 sentences"):
        service.record_selection(
            sample.sample_id,
            selected_ordinal=1,
            reason="One. Two. Three. Four.",
        )
