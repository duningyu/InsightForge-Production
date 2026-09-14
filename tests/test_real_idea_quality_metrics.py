import pytest

from app.services.real_idea_metrics import GoldSetNotFinalError, RealIdeaMetricsService


@pytest.fixture
def metrics_service():
    return RealIdeaMetricsService(
        sample_id="sample-1",
        raw_idea="Students need a simple way to track internship applications and follow-ups.",
        reviewed_brief={
            "idea": "application tracker",
            "target_user": "students",
            "problem": "follow-ups are easy to miss",
            "desired_outcome": "know the next action",
        },
        provider_decision="ACCEPT_AS_IS",
        solutions=[
            {"id": "solution-1", "requirements": ["r1", "r2"], "decisions": {"automation": "low"}},
            {"id": "solution-2", "requirements": ["r2"], "decisions": {"automation": "medium"}},
            {"id": "solution-3", "requirements": ["r1"], "decisions": {"automation": "high"}},
        ],
        selected_solution_id="solution-2",
        annotations={
            "brief": {"r1": True, "r2": True},
            "claims": [],
            "inheritance": {"solution_to_prd": 1.0, "prd_to_techdoc": 1.0, "prd_techdoc_to_handoff": 1.0},
        },
    )


def test_gold_set_requires_post_review_provider_confirmation(metrics_service):
    with pytest.raises(GoldSetNotFinalError):
        metrics_service.finalize_gold_set(source="llm_judge")

    gold = metrics_service.finalize_gold_set(source="idea_provider")
    assert {item.confirmed_by for item in gold.items} == {"idea_provider"}
    assert {item.source for item in gold.items} <= {"RAW_IDEA", "USER_CONFIRMED_BRIEF"}


def test_recall_and_zero_source_factuality_metrics(metrics_service):
    metrics_service.finalize_gold_set(source="idea_provider")
    metrics = metrics_service.evaluate()
    assert metrics.brief_critical_requirement_recall == pytest.approx(1.0)
    assert metrics.solution_set_recall >= 0.0
    assert metrics.unsupported_claim_rate == 0.0
    assert metrics.llm_judge_is_not_ground_truth is True
    assert metrics.requirement_recall_is_not_retrieval_recall is True


def test_selected_solution_and_inheritance_metrics_are_distinct(metrics_service):
    metrics_service.finalize_gold_set(source="idea_provider")
    metrics = metrics_service.evaluate()
    assert metrics.selected_solution_recall <= metrics.solution_set_recall
    assert metrics.solution_to_prd_inheritance == pytest.approx(1.0)
    assert metrics.prd_to_techdoc_inheritance == pytest.approx(1.0)
    assert metrics.handoff_decision_binding_accuracy == pytest.approx(1.0)
