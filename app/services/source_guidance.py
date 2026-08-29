from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceCategory:
    id: str
    label: str
    source_type: str
    authority: float
    authority_label: str
    authority_basis: str
    allowed_claims: str
    limitations: str
    example: str
    needs_confirmation: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "source_type": self.source_type,
            "authority": self.authority,
            "authority_label": self.authority_label,
            "authority_basis": self.authority_basis,
            "allowed_claims": self.allowed_claims,
            "limitations": self.limitations,
            "example": self.example,
            "needs_confirmation": self.needs_confirmation,
            "help": (
                f"能证明什么：{self.allowed_claims}；"
                f"不能证明什么：{self.limitations}"
            ),
        }


_CATEGORIES: dict[str, SourceCategory] = {
    "real_interview": SourceCategory(
        id="real_interview",
        label="真实访谈或真实用户反馈",
        source_type="real_user_research",
        authority=0.85,
        authority_label="high",
        authority_basis="一手用户资料；仍需保留样本范围、时间和原始记录。",
        allowed_claims="可支持该样本中的用户行为、问题和原话。",
        limitations="不能由少量样本直接外推整体市场比例或普遍需求。",
        example="访谈纪要、授权问卷、用户测试观察记录。",
    ),
    "official_page": SourceCategory(
        id="official_page",
        label="产品官网或官方说明",
        source_type="public_source",
        authority=0.75,
        authority_label="medium",
        authority_basis="官方公开页面，可复核其公开定位和功能陈述。",
        allowed_claims="可证明该机构公开展示或声明了某项能力。",
        limitations="不能证明用户真实需要、实际效果或第三方认可。",
        example="产品官网、官方帮助中心、官方发布说明。",
    ),
    "public_report": SourceCategory(
        id="public_report",
        label="公开报告、论文或行业文章",
        source_type="public_source",
        authority=0.70,
        authority_label="medium",
        authority_basis="公开可复核资料；可信度取决于作者、方法、时间和原始数据。",
        allowed_claims="可支持资料中明确陈述且适用范围一致的公开事实。",
        limitations="不能自动替代一手用户研究，也不能忽略发布日期和研究方法。",
        example="研究论文、行业报告、可信媒体分析。",
    ),
    "owner_input": SourceCategory(
        id="owner_input",
        label="我自己的需求、目标或限制",
        source_type="user_input",
        authority=0.90,
        authority_label="high",
        authority_basis="项目所有者明确确认的项目输入。",
        allowed_claims="可定义本项目的目标、范围、预算和约束。",
        limitations="只代表项目决策，不等于市场事实或用户普遍需求。",
        example="项目目标、截止时间、可用预算、必须使用的技术。",
    ),
    "simulation": SourceCategory(
        id="simulation",
        label="人工构造的演示或模拟材料",
        source_type="simulated_research",
        authority=0.40,
        authority_label="low",
        authority_basis="人工构造场景，仅用于流程演示或测试。",
        allowed_claims="可说明系统如何处理某类假设场景。",
        limitations="不能表述为真实访谈、真实用户反馈或市场验证。",
        example="模拟访谈、合成用户故事、演示案例。",
    ),
    "model_output": SourceCategory(
        id="model_output",
        label="AI 生成的分析或猜测",
        source_type="model_hypothesis",
        authority=0.25,
        authority_label="low",
        authority_basis="模型生成内容，没有独立来源链。",
        allowed_claims="只能作为待验证方向、问题清单或备选假设。",
        limitations="不能直接作为事实、用户研究或竞品能力证明。",
        example="AI 推测的用户痛点、未经搜索核对的市场判断。",
    ),
    "implementation": SourceCategory(
        id="implementation",
        label="代码、测试或运行结果",
        source_type="implementation_evidence",
        authority=0.85,
        authority_label="high",
        authority_basis="可复核的实现、测试或运行证据。",
        allowed_claims="可证明某项功能在指定版本中被实现或测试。",
        limitations="不能证明用户价值、市场需求、线上效果或生产级稳定性。",
        example="README、测试报告、接口返回、代码提交记录。",
    ),
    "unknown": SourceCategory(
        id="unknown",
        label="我不确定这是什么资料",
        source_type="user_input",
        authority=0.35,
        authority_label="low",
        authority_basis="来源不明，暂定为低可信项目输入，必须由用户确认后再用于强主张。",
        allowed_claims="暂时只可作为待整理的上下文。",
        limitations="在来源、作者和时间未确认前，不能支持事实性结论。",
        example="来源丢失的摘录、聊天截图、无法确认出处的笔记。",
        needs_confirmation=True,
    ),
}


class SourceGuidanceService:
    """Translate novice source descriptions into explicit governance proposals."""

    def describe_categories(self) -> list[dict[str, Any]]:
        return [category.as_dict() for category in _CATEGORIES.values()]

    def classify(
        self,
        *,
        origin_kind: str,
        title: str,
        source_url: str | None,
        publisher: str | None = None,
        published_at: str | None = None,
        filename: str,
        content: str,
    ) -> dict[str, Any]:
        try:
            category = _CATEGORIES[origin_kind]
        except KeyError as exc:
            raise ValueError(f"unknown source origin kind: {origin_kind}") from exc
        if not title.strip() or not filename.strip() or not content.strip():
            raise ValueError("title, filename, and content are required")

        proposal = category.as_dict()
        normalized_content = f"{title}\n{content}".lower()
        synthetic_markers = ("模拟", "合成", "非真实", "synthetic", "simulated", "not real")
        if origin_kind == "real_interview" and any(marker in normalized_content for marker in synthetic_markers):
            simulated = _CATEGORIES["simulation"].as_dict()
            simulated.update(
                {
                    "needs_confirmation": True,
                    "authority_basis": "资料正文标注为模拟或合成材料，不能按真实访谈赋予高可信度。",
                    "classification_reason": "正文包含模拟/合成声明，系统将用户选择的真实访谈降级为模拟材料。",
                }
            )
            return simulated
        if origin_kind == "official_page" and not source_url:
            proposal.update(
                {
                    "authority": 0.40,
                    "authority_label": "low",
                    "needs_confirmation": True,
                    "authority_basis": "未提供可复核 URL，暂按低可信公开资料保存，等待补充链接或原始文件。",
                }
            )
        if origin_kind == "real_interview" and (not publisher or not published_at):
            proposal.update(
                {
                    "authority": 0.40,
                    "authority_label": "low",
                    "needs_confirmation": True,
                    "authority_basis": "缺少受访者编号或记录日期，暂不能按可复核真实访谈赋予高可信度。",
                }
            )
        # Unknown materials with a URL are still only provisional public sources.
        if origin_kind == "unknown" and source_url:
            proposal.update(
                {
                    "source_type": "public_source",
                    "authority": 0.40,
                    "authority_label": "low",
                    "authority_basis": (
                        "存在 URL，但发布者和内容性质未知，暂定为低可信公开来源，必须人工确认。"
                    ),
                }
            )
        proposal["classification_reason"] = (
            f"用户选择“{category.label}”；系统按公开规则映射为 "
            f"{proposal['source_type']}。"
        )
        return proposal
