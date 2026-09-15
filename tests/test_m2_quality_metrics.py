from __future__ import annotations

import pytest

from app.services.if_guide_m2_quality import evaluate_prototype_task


def _payload(*, fabricated_dependency: bool = False) -> dict:
    return {
        "scope": ["记录一次流程", "保存结果"],
        "inputs": ["用户确认的范围"],
        "outputs": ["可检查的任务说明"],
        "existing_behaviors_to_preserve": ["现有目的与首个行动"],
        "explicit_non_goals": ["自动部署"],
        "known_technical_context": ["CONFIRMED: 来源于已确认的 Build Slice。"],
        "unknown_dependencies": ["具体布局待实现时确认"],
        "implementation_tasks": ["记录一次流程", "保存结果"],
        "acceptance_steps": ["输入范围", "执行流程", "检查结果"],
        "failure_recovery_notes": ["版本过期时重新加载"],
        "required_return_evidence": ["返回可检查的结果"],
        "permission_risk_notes": ["不执行外部动作"],
        "quality_rubric": {
            "rubric_version": "if-guide-m2-quality-v1",
            "evidence_ids": ["task:prototype-1:r2", "slice:slice-1:r2"],
            "scope": {
                "confirmed_item_ids": ["scope-1", "scope-2", "scope-3"],
                "represented_item_ids": ["scope-1", "scope-2"],
                "task_item_ids": ["scope-1", "scope-2", "scope-4"],
            },
            "critical_build_item_ids": ["accept-1", "accept-2", "accept-3"],
            "covered_acceptance_item_ids": ["accept-1", "accept-2"],
            "acceptance_testability": [
                {
                    "id": "accept-1",
                    "precondition": "已有范围",
                    "action": "保存范围",
                    "expected_result": "范围可恢复",
                    "failure_interpretation": "保存失败",
                },
                {
                    "id": "accept-2",
                    "precondition": "已有范围",
                    "action": "刷新页面",
                    "expected_result": "范围仍存在",
                    "failure_interpretation": "刷新后丢失",
                },
            ],
            "constraints": {
                "required_ids": ["constraint-1", "constraint-2", "constraint-3"],
                "preserved_ids": ["constraint-1", "constraint-2"],
                "contradicted_ids": ["constraint-2"],
            },
            "dependencies": [
                {"id": "dependency-1", "status": "UNKNOWN"},
                {
                    "id": "dependency-2",
                    "status": "KNOWN",
                    "verified": not fabricated_dependency,
                },
            ],
            "claims": [
                {"id": "claim-1", "class": "SUPPORTED_FACT", "presented_as_fact": True},
                {"id": "claim-2", "class": "MODEL_HYPOTHESIS", "presented_as_fact": False},
                {"id": "claim-3", "class": "USER_INPUT", "presented_as_fact": True},
            ],
        },
    }


def test_p1_metrics_use_explicit_item_denominators_and_safe_evidence():
    result = evaluate_prototype_task(_payload())

    assert result["status"] == "PASS"
    assert result["rubric_version"] == "if-guide-m2-quality-v1"
    assert result["evidence_ids"] == ["task:prototype-1:r2", "slice:slice-1:r2"]
    assert result["metrics"] == {
        "scope_recall": 2 / 3,
        "scope_precision": 2 / 3,
        "acceptance_coverage": 2 / 3,
        "acceptance_testability": 1.0,
        "constraint_preservation": 1 / 3,
        "dependency_clarity": 1.0,
        "unsupported_claim_rate": 0.0,
    }
    assert result["metric_details"]["scope_recall"] == {
        "numerator": 2,
        "denominator": 3,
        "item_ids": ["scope-1", "scope-2"],
    }
    assert result["metric_details"]["acceptance_coverage"] == {
        "numerator": 2,
        "denominator": 3,
        "item_ids": ["accept-1", "accept-2"],
    }


def test_p1_metrics_do_not_count_disclosed_hypothesis_as_unsupported_fact():
    payload = _payload()
    payload["quality_rubric"]["claims"] = [
        {"id": "hypothesis", "class": "MODEL_HYPOTHESIS", "presented_as_fact": False},
    ]

    result = evaluate_prototype_task(payload)

    assert result["status"] == "PASS"
    assert result["metrics"]["unsupported_claim_rate"] == 0.0
    assert result["metric_details"]["unsupported_claim_rate"] == {
        "numerator": 0,
        "denominator": 0,
        "item_ids": [],
    }


def test_fabricated_dependency_marked_verified_is_a_p0_failure():
    result = evaluate_prototype_task(_payload(fabricated_dependency=True))

    assert result["status"] == "FAIL"
    assert "M2_FABRICATED_DEPENDENCY_MARKED_VERIFIED" in result["codes"]

