from __future__ import annotations

import re
from typing import Any


def _snippet(text: str, limit: int = 220) -> str:
    compact = " ".join(str(text).split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _source_line(item: dict[str, Any]) -> str:
    source_url = f"，url={item['source_url']}" if item.get("source_url") else ""
    return (
        f"- **{item['source_title']}**：{_snippet(item['content'])} "
        f"（source_type=`{item['source_type']}`，authority={float(item['authority']):.2f}"
        f"{source_url}） {item['citation']}"
    )


def _evidence_link(item: dict[str, Any], *, relation: str = "supports") -> dict[str, Any]:
    return {
        "citation": item["citation"],
        "source_id": item["source_id"],
        "chunk_id": item["chunk_id"],
        "source_type": item["source_type"],
        "source_title": item["source_title"],
        "retrieval_run_id": item.get("retrieval_run_id"),
        "relation": relation,
    }


def _claim(
    *,
    section: str,
    text: str,
    claim_type: str,
    support_status: str,
    explanation: str,
    evidence: list[dict[str, Any]] | None = None,
    category: str,
    expected_source_types: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "section": section,
        "claim_text": text.strip(),
        "claim_type": claim_type,
        "support_status": support_status,
        "explanation": explanation,
        "evidence": evidence or [],
        "metadata": {
            "category": category,
            "expected_source_types": expected_source_types or [],
        },
    }


def _pick_evidence(
    evidence: list[dict[str, Any]],
    *,
    source_types: list[str],
    keywords: list[str] | None = None,
) -> dict[str, Any] | None:
    keywords = [item.lower() for item in (keywords or []) if item]
    candidates = [item for item in evidence if item.get("source_type") in source_types]
    if not candidates:
        return None

    def score(item: dict[str, Any]) -> tuple[float, float, str]:
        haystack = f"{item.get('source_title', '')} {item.get('content', '')}".lower()
        lexical = sum(1.0 for token in keywords if token in haystack)
        return (
            lexical,
            float(item.get("hybrid_score", 0.0)),
            str(item.get("chunk_id", "")),
        )

    return max(candidates, key=score)


def _render_source_claim(claim: dict[str, Any]) -> str:
    citations = " ".join(item["citation"] for item in claim.get("evidence", []))
    source_types = sorted({item["source_type"] for item in claim.get("evidence", [])})
    disclosure = f"（source_type=`{'`,`'.join(source_types)}`）" if source_types else ""
    return f"{claim['claim_text']} {citations}{disclosure}".strip()


def _render_user_claim(claim: dict[str, Any]) -> str:
    return f"{claim['claim_text']}（来源：用户已确认的项目画布）"


_REQUIRED_PRD_HEADINGS = [
    "## 1. 文档边界与来源说明",
    "## 2. 背景与问题",
    "## 3. 目标用户",
    "## 4. 产品目标",
    "## 7. 功能需求",
    "## 9. 指标与验收",
    "## 11. 证据索引",
]
_REQUIRED_TECHDOC_HEADINGS = [
    "## 1. 技术目标与边界",
    "## 2. 总体架构",
    "## 3. 数据模型",
    "## 5. RAG 检索",
    "## 6. 文档生成与质量 Loop",
    "## 11. 证据索引",
]


class LocalDocumentGenerator:
    """Deterministic generator with a structured claim/evidence ledger.

    Source-backed paragraphs quote or summarize one retrieved excerpt selected
    by source type and lexical fit. Canvas statements are explicitly marked as
    user-confirmed. Design proposals are labelled as suggestions rather than
    facts. This removes the former index-based citation rotation behavior.
    """

    def generate(
        self,
        doc_type: str,
        canvas: dict[str, Any],
        evidence: list[dict[str, Any]],
        *,
        project_title: str = "InsightForge",
    ) -> dict[str, Any]:
        if doc_type not in {"prd", "techdoc"}:
            raise ValueError("doc_type must be prd or techdoc")
        if doc_type == "prd":
            content, claims = self._generate_prd(project_title, canvas, evidence)
        else:
            content, claims = self._generate_techdoc(project_title, canvas, evidence)
        citations = sorted(
            {
                match
                for match in re.findall(r"\[source:[^\]\s]+#chunk:[^\]\s]+\]", content)
            }
        )
        return {"content": content, "citations": citations, "claims": claims}

    def _common_claims(
        self,
        canvas: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        problem = _claim(
            section="背景与问题",
            text=str(canvas.get("problem", "")),
            claim_type="user_confirmed",
            support_status="confirmed_by_canvas",
            explanation="该内容来自当前文档绑定的 Canvas 版本，不是模型推断。",
            category="problem",
        )
        target = _claim(
            section="目标用户",
            text=str(canvas.get("target_users", "")),
            claim_type="user_confirmed",
            support_status="confirmed_by_canvas",
            explanation="该目标用户由项目创建者在 Canvas 中确认。",
            category="target_users",
        )

        public_item = _pick_evidence(
            evidence,
            source_types=["public_source"],
            keywords=["竞品", "公开", "差异", "引用", "版本"],
        )
        public = _claim(
            section="背景与问题",
            text=(
                f"公开资料片段记录：{_snippet(public_item['content'], 260)}"
                if public_item
                else "当前没有可用于市场或竞品背景的公开来源；相关判断仍待补证。"
            ),
            claim_type="source_backed" if public_item else "unresolved",
            support_status="supported_by_source_excerpt" if public_item else "missing_evidence",
            explanation=(
                "该段仅复述项目内公开来源片段，不将其扩大为完整市场研究结论。"
                if public_item
                else "未检索到 public_source，系统不生成确定性竞品结论。"
            ),
            evidence=[_evidence_link(public_item)] if public_item else [],
            category="public_context",
            expected_source_types=["public_source"],
        )

        implementation_item = _pick_evidence(
            evidence,
            source_types=["implementation_evidence"],
            keywords=["实现", "MVP", "API", "测试", "SQLite", "MCP"],
        )
        implementation = _claim(
            section="实现状态",
            text=(
                f"实现证据片段记录：{_snippet(implementation_item['content'], 300)}"
                if implementation_item
                else "当前没有实现证据，因此不能把规划能力写成已完成功能。"
            ),
            claim_type="source_backed" if implementation_item else "unresolved",
            support_status=(
                "supported_by_source_excerpt" if implementation_item else "missing_evidence"
            ),
            explanation=(
                "implementation_evidence 只支持当前代码或测试状态，不证明用户价值。"
                if implementation_item
                else "未检索到 implementation_evidence。"
            ),
            evidence=[_evidence_link(implementation_item)] if implementation_item else [],
            category="implementation_status",
            expected_source_types=["implementation_evidence"],
        )

        simulated_item = _pick_evidence(
            evidence,
            source_types=["simulated_research"],
            keywords=["模拟", "用户", "痛点", "来源", "版本"],
        )
        simulated = _claim(
            section="目标用户",
            text=(
                "模拟/人工构造材料（不代表真实用户调研）记录："
                f"{_snippet(simulated_item['content'], 260)}"
                if simulated_item
                else "当前没有模拟材料；系统不补写虚构用户反馈。"
            ),
            claim_type="source_backed" if simulated_item else "unresolved",
            support_status="supported_by_source_excerpt" if simulated_item else "missing_evidence",
            explanation=(
                "该材料只能用于演示潜在场景，不能写成真实用户结论。"
                if simulated_item
                else "未检索到 simulated_research。"
            ),
            evidence=[_evidence_link(simulated_item)] if simulated_item else [],
            category="simulated_pain_point",
            expected_source_types=["simulated_research"],
        )
        return {
            "problem": problem,
            "target": target,
            "public": public,
            "implementation": implementation,
            "simulated": simulated,
        }

    def _generate_prd(
        self,
        project_title: str,
        canvas: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        common = self._common_claims(canvas, evidence)
        claims: list[dict[str, Any]] = list(common.values())

        goal_claims = [
            _claim(
                section="产品目标",
                text=str(goal),
                claim_type="user_confirmed",
                support_status="confirmed_by_canvas",
                explanation="该目标来自绑定的 Canvas 版本。",
                category="goal",
            )
            for goal in canvas.get("goals", [])
        ]
        metric_claims = [
            _claim(
                section="指标与验收",
                text=str(metric),
                claim_type="user_confirmed",
                support_status="confirmed_by_canvas",
                explanation="该验收指标来自绑定的 Canvas 版本。",
                category="success_metric",
            )
            for metric in canvas.get("success_metrics", [])
        ]
        suggested_flow = _claim(
            section="核心用户流程",
            text=(
                "【系统建议，待产品复核】采用“描述想法 → 分步澄清 → 补充证据 → "
                "比较方案 → 确认 Canvas → 生成与审查文档 → AI Coding 交接”的主流程。"
            ),
            claim_type="model_suggestion",
            support_status="proposal_requires_confirmation",
            explanation="这是基于当前 Canvas 的产品设计建议，不是外部事实。",
            category="suggested_flow",
        )
        claims.extend(goal_claims + metric_claims + [suggested_flow])

        goals = "\n".join(f"- {_render_user_claim(item)}" for item in goal_claims) or "- 暂未确认"
        non_goals = "\n".join(f"- {item}" for item in canvas.get("non_goals", [])) or "- 暂未确认"
        metrics = "\n".join(f"- {_render_user_claim(item)}" for item in metric_claims) or "- 暂未确认"
        constraints = "\n".join(f"- {item}" for item in canvas.get("constraints", [])) or "- 暂未确认"
        evidence_index = "\n".join(_source_line(item) for item in evidence) or "- 当前无可引用来源。"

        content = f"""# {project_title} 产品需求文档（PRD）

## 1. 文档边界与来源说明

本文档把内容分为四类：**用户已确认**、**来源片段支持**、**系统建议**和**待补证**。`simulated_research` 是人工构造材料；`model_hypothesis` 是待验证假设；`implementation_evidence` 只证明实现状态，不证明业务价值。引用合法不等于语义充分支持，重要结论仍需人工复核。

## 2. 背景与问题

{_render_user_claim(common['problem'])}

{_render_source_claim(common['public']) if common['public']['evidence'] else common['public']['claim_text']}

## 3. 目标用户

{_render_user_claim(common['target'])}

{_render_source_claim(common['simulated']) if common['simulated']['evidence'] else common['simulated']['claim_text']}

## 4. 产品目标

{goals}

## 5. 非目标

{non_goals}

## 6. 核心用户流程

{suggested_flow['claim_text']}

## 7. 功能需求

### 7.1 新手引导

- 【系统建议，待产品复核】一次只提出一个高价值问题，并说明“为什么问、示例是什么、不知道时怎么办”。
- 用户回答与系统建议分开保存；只有显式确认后才写入新的 Canvas 版本。

### 7.2 来源治理与检索追溯

- 【系统建议，待产品复核】新手模式使用“实际反馈、官网、公开报告、个人输入、模拟材料、实现证据”等可理解分类。
- 每次检索应展示查询、配置档位、Top-K 来源、权重、候选数、返回结果和参数依据。

### 7.3 文档、主张与证据

- 事实性段落必须能定位到 source ID 与 chunk ID。
- 主张账本区分 `user_confirmed`、`source_backed`、`model_suggestion` 和 `unresolved`。

### 7.4 当前实现证据

{_render_source_claim(common['implementation']) if common['implementation']['evidence'] else common['implementation']['claim_text']}

## 8. 业务规则与权限

- 模型不得自动审批、发布、删除或覆盖已批准版本。
- 单次用户反馈只能记录为定性输入，不能写成市场验证。
- 参数为工程基线时必须显示其来源与“尚未证明最优”的状态。

## 9. 指标与验收

{metrics}

附加审计指标：关键事实性主张可追溯率、无依据主张率、检索运行可回放率、Canvas 建议确认率、引导完成率和中途退出步骤。

## 10. 风险与回退

{constraints}

- 证据不足：把结论标记为待补证，不用高权威低相关来源填补。
- 来源冲突：同时展示支持与冲突证据，转人工裁决。
- 可选 LLM 不可用：回退到本地确定性生成，不改变来源和权限边界。

## 11. 证据索引

{evidence_index}
"""
        return content, claims

    def _generate_techdoc(
        self,
        project_title: str,
        canvas: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        common = self._common_claims(canvas, evidence)
        claims: list[dict[str, Any]] = list(common.values())
        architecture = _claim(
            section="总体架构",
            text=(
                "【系统建议，待技术复核】Browser Guided UI 与 Advanced Workspace 共享 FastAPI "
                "Domain Services、SQLite、Retrieval Trace、Claim Ledger、ToolRegistry 和 MCP 边界。"
            ),
            claim_type="model_suggestion",
            support_status="proposal_requires_confirmation",
            explanation="这是由产品合同推导的架构方案，不是实现完成证明。",
            category="architecture_proposal",
        )
        claims.append(architecture)
        evidence_index = "\n".join(_source_line(item) for item in evidence) or "- 当前无可引用来源。"

        content = f"""# {project_title} 技术设计文档（TechDoc）

## 1. 技术目标与边界

{_render_user_claim(common['problem'])}

目标用户：{_render_user_claim(common['target'])}

本 TechDoc 区分已实现状态、拟议架构与待验证项；引用存在不等于语义充分支持。

## 2. 总体架构

{architecture['claim_text']}

```text
Guided UI / Advanced Workspace
              |
           FastAPI
              |
  Guided Service | Source Service | Retrieval Trace
  Claim Ledger   | Document Loop  | Handoff Service
              |
            SQLite
              |
       ToolRegistry / MCP
```

当前实现状态只按 implementation_evidence 记录：

{_render_source_claim(common['implementation']) if common['implementation']['evidence'] else common['implementation']['claim_text']}

## 3. 数据模型

核心实体包括项目、Canvas 版本、来源与切片、引导会话与消息、检索运行与命中、文档版本、主张与证据链接、审批和交接运行。已批准文档保持不可变，新修改创建新版本。

## 4. 文档摄取

支持文本、Markdown、JSON、DOCX 和 PDF 的本地摄取。来源应保存 URL、发布者、发布时间、抓取时间、SHA-256、类型、权威性依据和状态；缺失元数据必须显式显示，而不是自动补造。

## 5. RAG 检索

- 配置档位集中管理；当前基线权重为 BM25 0.55、TF-IDF cosine 0.30、authority 0.15。
- 这些权重属于 `manual_baseline_not_frozen_best`，未通过冻结评测集证明最优。
- 每次运行保存 profile、Top-K、查询、候选数、返回命中、分项分数、actor 和时间。
- SQL 先按 `project_id` 与来源状态过滤；无词项相关性时 authority 不能单独产生召回。

公开背景证据示例：

{_render_source_claim(common['public']) if common['public']['evidence'] else common['public']['claim_text']}

## 6. 文档生成与质量 Loop

1. 使用显式、可回放的生成查询构建 Evidence Package。
2. 按来源类型与词项匹配选择支持片段，不再按列表位置轮换引用。
3. 生成 Markdown 与结构化 Claim Ledger。
4. Validator 检查章节、引用作用域、来源披露、Claim-Evidence 类型匹配和未解决主张。
5. 最多执行受控修复轮次；仍失败则 `needs_human_review`。
6. 保存检索运行 ID、文档版本、主张链接、验证问题和审计日志。

## 7. Function Calling 与权限

应用拥有工具注册、参数校验、执行、状态与审计权。L0 为只读；L1 可创建草稿或交接清单；L2 审批要求宿主显式人工确认。删除、外部发布和覆盖批准版本不注册为模型工具。

## 8. MCP Server

MCP 只提供标准化资源与工具连接，不承担事实真伪判断。可暴露 Canvas、来源、检索轨迹、Claim Ledger、文档版本和交接准备度；二进制交接导出仍由显式 HTTP/UI 操作触发。

## 9. API 与导出

API 覆盖引导、来源治理、检索与运行回放、文档生成、Claim Ledger、验证、审批、导出和交接准备度。错误采用 fail-closed：缺少项目、证据或批准文档时不生成伪完成状态。

## 10. 测试与验收

- 新手引导状态流与 Canvas 显式确认。
- 来源分类依据和元数据持久化。
- 检索 Profile 单一事实源、项目隔离与运行回放。
- Claim-Evidence 来源类型对齐和越界拒绝。
- 文档审批与 AI Coding 交接 Gate。

## 11. 证据索引

模拟材料（如存在）必须继续标注为人工构造，不代表真实用户研究：

{_render_source_claim(common['simulated']) if common['simulated']['evidence'] else common['simulated']['claim_text']}

{evidence_index}
"""
        return content, claims

    def repair(
        self,
        content: str,
        issues: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> str:
        repaired = content
        issue_codes = {issue["code"] for issue in issues}
        if "unsupported_real_research_claim" in issue_codes:
            repaired = repaired.replace(
                "真实用户调研证明",
                "模拟或待验证材料提示（不代表真实用户调研结论）",
            ).replace(
                "用户调研证明",
                "待验证材料提示（不代表真实用户调研结论）",
            )
        if "missing_citations" in issue_codes and evidence:
            repaired += "\n\n## 补充证据\n\n" + "\n".join(_source_line(item) for item in evidence[:5])
        if "source_type_not_disclosed" in issue_codes:
            repaired += (
                "\n\n> 来源治理补充：所有 simulated_research 均为人工构造模拟材料；"
                "所有 model_hypothesis 均为待验证假设。\n"
            )
        return repaired


def _strip_think(text: str) -> str:
    if "<think>" not in text and "<THINK>" not in text:
        return text
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


class LLMDocumentGenerator:
    """Optional OpenAI-compatible generator with conservative claim handling.

    A model-produced paragraph is not treated as semantically verified merely
    because it contains a valid citation. Such lines are persisted as unresolved
    claims and therefore require human review. Explicit LLM mode fails loudly on
    contract errors; deterministic_demo must be selected by the host.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 240.0,
    ):
        if not all(
            isinstance(value, str) and value.strip()
            for value in (base_url, model, api_key)
        ):
            raise RuntimeError(
                "Remote document generation requires explicit profile-backed configuration"
            )
        self.base_url = base_url.strip()
        self.model = model.strip()
        self.api_key = api_key
        self.timeout = timeout
        self._fallback = LocalDocumentGenerator()
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError('Install optional dependencies with: pip install -e ".[llm]"') from exc
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    def repair(
        self,
        content: str,
        issues: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> str:
        return self._fallback.repair(content, issues, evidence)

    def generate(
        self,
        doc_type: str,
        canvas: dict[str, Any],
        evidence: list[dict[str, Any]],
        *,
        project_title: str = "InsightForge",
    ) -> dict[str, Any]:
        required_headings = (
            _REQUIRED_PRD_HEADINGS if doc_type == "prd" else _REQUIRED_TECHDOC_HEADINGS
        )
        evidence_block = "\n".join(
            f"- {item.get('citation')}（source_type={item.get('source_type')}）："
            f"{str(item.get('content', ''))[:600]}"
            for item in evidence
        )
        canvas_block = "\n".join(
            f"- {key}：{value}"
            for key, value in (canvas or {}).items()
            if isinstance(value, (str, int, float))
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是证据优先的项目文档助手。保留引用与来源标签；"
                        "引用存在不代表语义已经验证；不得审批、发布或删除。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"为 {project_title} 生成 {'PRD' if doc_type == 'prd' else 'TechDoc'}。\n"
                        "必须包含以下标题：\n" + "\n".join(required_headings)
                        + "\n项目画布：\n" + canvas_block + "\n证据：\n" + evidence_block
                        + "\n只输出 Markdown。"
                    ),
                },
            ],
            temperature=0.3,
        )
        content = _strip_think(response.choices[0].message.content or "")
        citations = sorted(set(re.findall(r"\[source:[^\]\s]+#chunk:[^\]\s]+\]", content)))
        if not citations or not all(heading in content for heading in required_headings):
            raise RuntimeError("LLM_DOCUMENT_CONTRACT_FAILED")
        evidence_by_citation = {item["citation"]: item for item in evidence}
        claims: list[dict[str, Any]] = []
        for line in content.splitlines():
            line_citations = re.findall(r"\[source:[^\]\s]+#chunk:[^\]\s]+\]", line)
            if not line_citations or line.startswith("#"):
                continue
            links = [
                _evidence_link(evidence_by_citation[citation])
                for citation in line_citations if citation in evidence_by_citation
            ]
            claims.append(
                _claim(
                    section="LLM 生成段落", text=line.strip(), claim_type="unresolved",
                    support_status="retrieved_not_semantically_verified",
                    explanation="模型使用了项目内合法引用，但系统没有自动断言该片段在语义上充分支持整句。",
                    evidence=links, category="llm_cited_line", expected_source_types=[],
                )
            )
        return {"content": content, "citations": citations, "claims": claims}


def build_generator() -> "LocalDocumentGenerator | LLMDocumentGenerator":
    """Build only the profile-independent local document generator.

    Legacy OPENAI_* environment variables are not a model-profile selection and
    therefore cannot authorize a remote document request.  Document generation
    stays local until it is migrated through the per-project profile resolver.
    """
    return LocalDocumentGenerator()
