from app.schemas import IdeaBriefDraft


def _draft(**overrides):
    values = {
        "original_idea": "整理我收藏的 AI 工具和教程",
        "target_user": "经常收藏工具的个人用户",
        "problem": "收藏后容易忘记原因，也难以判断是否适合自己",
        "desired_outcome": "能集中整理并判断收藏内容",
        "provenance": {
            "original_idea": "user_input",
            "target_user": "model_hypothesis",
            "problem": "model_hypothesis",
            "desired_outcome": "model_hypothesis",
        },
    }
    values.update(overrides)
    return IdeaBriefDraft(**values)


def test_substantive_completeness_reports_all_required_missing_fields():
    result = _draft(target_user="", problem="", desired_outcome="").validate_substantive_completeness()

    assert result.complete is False
    assert result.missing_fields == ("target_user", "problem", "desired_outcome")


def test_clarification_required_brief_is_not_substantively_complete():
    result = _draft(
        clarification_required=True,
        clarification_question="谁是主要用户？",
    ).validate_substantive_completeness()

    assert result.complete is False
    assert result.clarification_required is True


def test_complete_brief_is_substantively_complete():
    result = _draft().validate_substantive_completeness()

    assert result.complete is True
    assert result.missing_fields == ()
