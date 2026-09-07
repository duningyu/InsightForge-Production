from __future__ import annotations

import re
from typing import Any

CITATION_RE = re.compile(r"\[source:[^\]\s]+#chunk:[^\]\s]+\]")

PRD_HEADINGS = [
    "## 1. 文档边界与来源说明",
    "## 2. 背景与问题",
    "## 3. 目标用户",
    "## 4. 产品目标",
    "## 7. 功能需求",
    "## 9. 指标与验收",
    "## 11. 证据索引",
]
TECHDOC_HEADINGS = [
    "## 1. 技术目标与边界",
    "## 2. 总体架构",
    "## 3. 数据模型",
    "## 5. RAG 检索",
    "## 6. 文档生成与质量 Loop",
    "## 11. 证据索引",
]


def _issue(code: str, message: str, *, severity: str = "error", section: str | None = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "section": section}


class DocumentValidator:
    def validate(
        self,
        *,
        content: str,
        valid_citations: dict[str, dict[str, Any]],
        canvas: dict[str, Any],
        doc_type: str | None = None,
        claims: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        citations = CITATION_RE.findall(content)
        no_source_disclosure = not citations and any(
            marker in content for marker in ("没有外部资料", "暂无来源", "仍待验证", "待验证")
        )
        if not citations:
            issues.append(
                _issue(
                    "missing_citations",
                    "document contains no source citations",
                    severity="warning" if no_source_disclosure else "error",
                )
            )
        invalid = sorted(set(citations) - valid_citations.keys())
        if invalid:
            issues.append(_issue("citation_out_of_scope", f"invalid citations: {invalid[:5]}"))

        required = PRD_HEADINGS if doc_type == "prd" else TECHDOC_HEADINGS if doc_type == "techdoc" else []
        for heading in required:
            if heading not in content:
                issues.append(_issue("missing_required_section", f"missing heading: {heading}", section=heading))

        qualifiers = ("模拟", "人工构造", "不代表", "未验证", "待验证", "不能", "无法", "并非")
        claim_patterns = ("真实用户调研证明", "真实用户研究证明", "用户调研证明", "调研显示", "访谈证明")
        for line in content.splitlines():
            if any(pattern in line for pattern in claim_patterns) and not any(q in line for q in qualifiers):
                issues.append(
                    _issue(
                        "unsupported_real_research_claim",
                        f"unqualified research claim: {line[:120]}",
                        section="claim_boundary",
                    )
                )
                break

        for line in content.splitlines():
            line_citations = CITATION_RE.findall(line)
            for citation in line_citations:
                metadata = valid_citations.get(citation)
                if not metadata:
                    continue
                source_type = metadata.get("source_type")
                if source_type == "simulated_research" and not (
                    "simulated_research" in line or "模拟" in line or "人工构造" in line
                ):
                    issues.append(
                        _issue(
                            "source_type_not_disclosed",
                            f"simulated source used without disclosure: {citation}",
                            section="source_governance",
                        )
                    )
                if source_type == "model_hypothesis" and not (
                    "model_hypothesis" in line or "假设" in line or "待验证" in line
                ):
                    issues.append(
                        _issue(
                            "source_type_not_disclosed",
                            f"hypothesis source used without disclosure: {citation}",
                            section="source_governance",
                        )
                    )

        for claim in claims or []:
            claim_type = str(claim.get("claim_type") or "unresolved")
            section = str(claim.get("section") or "claim_ledger")
            evidence = list(claim.get("evidence") or [])
            metadata = dict(claim.get("metadata") or {})
            if claim_type == "source_backed":
                if not evidence:
                    issues.append(
                        _issue(
                            "claim_missing_evidence",
                            f"source-backed claim has no evidence: {str(claim.get('claim_text', ''))[:120]}",
                            section=section,
                        )
                    )
                    continue
                expected_types = set(metadata.get("expected_source_types") or [])
                actual_types: set[str] = set()
                for link in evidence:
                    citation = str(link.get("citation") or "")
                    citation_metadata = valid_citations.get(citation)
                    if citation_metadata is None:
                        issues.append(
                            _issue(
                                "claim_citation_out_of_scope",
                                f"claim uses invalid citation: {citation}",
                                section=section,
                            )
                        )
                        continue
                    actual_types.add(str(citation_metadata.get("source_type") or ""))
                if expected_types and not actual_types.issubset(expected_types):
                    issues.append(
                        _issue(
                            "claim_source_type_mismatch",
                            f"expected source types {sorted(expected_types)}, got {sorted(actual_types)}",
                            section=section,
                        )
                    )
                if claim.get("support_status") != "supported_by_source_excerpt":
                    issues.append(
                        _issue(
                            "claim_support_unverified",
                            "source-backed claim is not marked as supported by a source excerpt",
                            section=section,
                        )
                    )
                if "simulated_research" in actual_types and not any(
                    qualifier in str(claim.get("claim_text") or "")
                    for qualifier in ("模拟", "人工构造", "不代表真实")
                ):
                    issues.append(
                        _issue(
                            "claim_simulation_not_disclosed",
                            "simulated evidence is not disclosed in the claim text",
                            section=section,
                        )
                    )
            elif claim_type == "unresolved":
                issues.append(
                    _issue(
                        "unresolved_claim_requires_review",
                        f"unresolved claim: {str(claim.get('claim_text', ''))[:120]}",
                        severity="warning" if no_source_disclosure else "error",
                        section=section,
                    )
                )

        if canvas:
            problem = str(canvas.get("problem", "")).strip()
            target_users = str(canvas.get("target_users", "")).strip()
            if problem and problem[: min(24, len(problem))] not in content:
                issues.append(_issue("canvas_problem_missing", "canvas problem is not represented"))
            if target_users and target_users[: min(18, len(target_users))] not in content:
                issues.append(_issue("canvas_target_users_missing", "canvas target users are not represented"))

        unique: dict[tuple[str, str | None], dict[str, Any]] = {}
        for item in issues:
            unique[(item["code"], item.get("section"))] = item
        return list(unique.values())
