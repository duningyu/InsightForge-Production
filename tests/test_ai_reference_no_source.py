import json

from app.db import Database
from app.schemas import AIReferenceDraft
from app.services.ai_reference import AIReferenceService
from app.services.document_versions import DocumentVersionService
from app.services.handoff import HandoffService
from app.services.generation import LocalDocumentGenerator
from app.services.loop import DocumentLoop
from app.services.projects import ProjectService
from app.services.validation import DocumentValidator


class FakeReferenceRuntime:
    mode = "fake"
    provider = "fake-transport"
    model = "synthetic-model"
    prompt_version = "test"
    schema_version = "test"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 1

    def __init__(self):
        self.calls = []

    def generate_ai_reference(self, context):
        self.calls.append(context)
        return AIReferenceDraft(
            possible_target_users=["第一次找实习的学生"],
            possible_scenarios=["准备投递前整理简历"],
            possible_user_problems=["不知道如何针对岗位修改简历"],
            missing_information=["尚未确认真实用户是否遇到这个问题"],
            mvp_thoughts=["先提供逐步整理流程"],
            questions_to_validate=["目标用户是否愿意持续使用"],
            research_directions=["访谈3至5名目标用户"],
        )


def test_ai_reference_is_bounded_and_not_a_source(tmp_path):
    db = Database(tmp_path / "reference.sqlite3")
    db.init_schema()
    project_id = ProjectService(db).create_project(
        title="合成无资料项目", summary="只有想法，没有来源。", actor="synthetic-user"
    )["id"]
    runtime = FakeReferenceRuntime()
    service = AIReferenceService(db)

    result = service.generate(project_id, actor="synthetic-user", runtime=runtime)
    assert len(runtime.calls) == 1
    assert result["status"] == "completed"
    assert result["is_evidence"] is False
    assert result["result"]["uncertainty_notice"] == "AI生成参考，尚未经外部资料核实。"
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sources")["n"] == 0

    applied = service.apply(
        project_id,
        reference_id=result["id"],
        actor="synthetic-user",
        decisions=[
            {"category": "possible_target_users", "item": "第一次找实习的学生", "decision": "adopt", "rationale": "先作为假设"}
        ],
    )
    assert applied["status"] == "applied"
    assert applied["decisions"][0]["provenance"] == "AI_REFERENCE"
    assert service.get_context(project_id, actor="synthetic-user")["adopted"][0]["item"] == "第一次找实习的学生"


def test_no_source_disclosure_is_warning_but_structural_issue_still_blocks():
    validator = DocumentValidator()
    content = """## 1. 文档边界与来源说明
当前项目没有外部资料，以下判断均为项目假设，仍待验证。
## 2. 背景与问题
问题待确认。
## 3. 目标用户
目标用户待确认。
## 4. 产品目标
先形成可验证的最小方案。
## 7. 功能需求
记录待确认事项。
## 9. 指标与验收
指标待验证。
## 11. 证据索引
暂无来源，不能据此声称已经验证。
"""
    issues = validator.validate(
        content=content,
        valid_citations={},
        canvas={},
        doc_type="prd",
        claims=[{
            "claim_type": "unresolved",
            "claim_text": "目标用户仍待验证",
            "section": "目标用户",
            "evidence": [],
        }],
    )
    assert {issue["code"] for issue in issues} == {
        "missing_citations",
        "unresolved_claim_requires_review",
    }
    assert all(issue["severity"] == "warning" for issue in issues)

    broken = validator.validate(
        content=content.replace("## 7. 功能需求", ""),
        valid_citations={},
        canvas={},
        doc_type="prd",
        claims=[],
    )
    assert any(issue["code"] == "missing_required_section" and issue["severity"] == "error" for issue in broken)


def test_zero_source_project_can_be_confirmed_and_handed_off_with_boundaries(tmp_path):
    db = Database(tmp_path / "zero-source.sqlite3")
    db.init_schema()
    actor = "synthetic-user"
    project_id = ProjectService(db).create_project(
        title="无资料可交接项目", summary="只有一个待验证想法。", actor=actor
    )["id"]
    ProjectService(db).update_canvas(
        project_id,
        problem="初学者不知道如何把模糊想法整理成下一步",
        target_users="需要开始探索想法的初学者",
        goals=["形成可讨论的最小方案"],
        non_goals=["不声称市场事实已验证"],
        success_metrics=["能够列出下一步验证问题"],
        constraints=[],
        actor=actor,
    )

    loop = DocumentLoop(db, generator=LocalDocumentGenerator())
    generated = {
        doc_type: loop.run(project_id, doc_type, idempotency_key=f"zero-source-{doc_type}")
        for doc_type in ("prd", "techdoc")
    }
    assert all(item["terminal_state"] == "completed" for item in generated.values())
    assert all(item["validation_status"] == "passed" for item in generated.values())
    assert all(item["issues"] and all(issue["severity"] == "warning" for issue in item["issues"]) for item in generated.values())
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sources WHERE project_id=?", (project_id,))["n"] == 0

    versions = DocumentVersionService(db)
    for item in generated.values():
        versions.confirm(item["version_id"], actor=actor, human_confirmed=True, note="明确了解待确认事项")

    handoff = HandoffService(db)
    before_ack = handoff.readiness(project_id)
    assert before_ack["ready"] is False
    assert any(item["code"] == "unresolved_items_acknowledgement_required" for item in before_ack["missing"])
    acknowledgement = handoff.acknowledge_unresolved(
        project_id, actor=actor, confirmed=True, note="我已了解当前版本仍有待确认事项"
    )
    assert acknowledgement["status"] == "acknowledged"
    ready = handoff.readiness(project_id)
    assert ready["ready"] is True
    payload, manifest = handoff.build_zip(project_id, target_client="generic", actor=actor)
    assert manifest["human_acknowledgement"]["actor"] == actor
    assert manifest["unresolved_items"]
    import zipfile
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert "UNRESOLVED_RISKS.md" in archive.namelist()
        assert "待确认" in archive.read("UNRESOLVED_RISKS.md").decode("utf-8")
