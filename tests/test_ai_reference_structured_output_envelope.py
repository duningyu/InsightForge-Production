import pytest
from pydantic import ValidationError

from app.schemas import AIReferenceDraft
from app.services.generation_contracts import (
    AIReferenceProviderEnvelope,
    AIReferenceProviderReference,
    REFERENCE_FIELDS,
    map_ai_reference_provider_envelope,
)


def test_provider_facing_schema_exposes_reference_category_enum():
    schema = AIReferenceProviderEnvelope.model_json_schema()
    item_schema = schema["$defs"][AIReferenceProviderReference.__name__]
    category_schema = item_schema["properties"]["category"]

    assert set(category_schema["enum"]) == set(REFERENCE_FIELDS)


def test_provider_envelope_requires_substantive_reference_item():
    with pytest.raises(ValidationError):
        AIReferenceProviderEnvelope.model_validate(
            {"uncertainty_notice": "信息有限，仍需验证。", "references": []}
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"references": [], "uncertainty_notice": "信息有限。"},
        {"references": [{"category": "mvp_thoughts", "content": "   "}]},
        {"references": [{"category": "unexpected_advice", "content": "不应接受"}]},
        {"references": [{"category": "mvp_thoughts", "content": "建议"}], "extra": "禁止"},
    ],
)
def test_provider_envelope_rejects_non_contract_shapes(payload):
    with pytest.raises(ValidationError):
        AIReferenceProviderEnvelope.model_validate(payload)


def test_notice_only_provider_payload_is_rejected_before_domain_mapping():
    with pytest.raises(ValidationError):
        AIReferenceProviderEnvelope.model_validate(
            {
                "uncertainty_notice": "信息有限，仍需验证。",
                "references": [],
            }
        )


def test_valid_provider_envelope_maps_to_unchanged_domain_model():
    envelope = AIReferenceProviderEnvelope.model_validate(
        {
            "references": [
                {"category": "mvp_thoughts", "content": "先记录投递阶段并提示下一步跟进。"},
                {"category": "questions_to_validate", "content": "学生是否愿意持续更新进度？"},
            ],
            "uncertainty_notice": "这些是基于当前想法的 AI 建议，仍需验证。",
        }
    )

    draft = map_ai_reference_provider_envelope(envelope)

    assert isinstance(draft, AIReferenceDraft)
    assert draft.mvp_thoughts == ["先记录投递阶段并提示下一步跟进。"]
    assert draft.questions_to_validate == ["学生是否愿意持续更新进度？"]
    assert draft.uncertainty_notice == "这些是基于当前想法的 AI 建议，仍需验证。"
