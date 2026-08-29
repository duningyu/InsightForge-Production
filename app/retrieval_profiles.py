from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalProfile:
    id: str
    label: str
    description: str
    top_k: int
    bm25_weight: float = 0.55
    cosine_weight: float = 0.30
    authority_weight: float = 0.15
    selection_basis: str = (
        "当前数值来自可运行本地基线与工程经验，未通过冻结评测集证明最优。"
    )
    validation_status: str = "manual_baseline_not_frozen_best"
    tradeoff: str = ""

    @property
    def weights(self) -> dict[str, float]:
        return {
            "bm25": self.bm25_weight,
            "cosine": self.cosine_weight,
            "authority": self.authority_weight,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["weights"] = self.weights
        return payload


_PROFILES: dict[str, RetrievalProfile] = {
    "quick_explore_v1": RetrievalProfile(
        id="quick_explore_v1",
        label="快速了解",
        description="返回较少结果，适合先确认资料方向，不用于最终证据审查。",
        top_k=4,
        tradeoff="速度和可读性更好，但更容易漏掉弱相关证据。",
    ),
    "balanced_traceable_v1": RetrievalProfile(
        id="balanced_traceable_v1",
        label="平衡查证",
        description="默认模式；在召回数量与人工阅读负担之间保持平衡。",
        top_k=8,
        tradeoff="结果数量适中，但仍需要通过评测集验证是否适合具体项目。",
    ),
    "thorough_review_v1": RetrievalProfile(
        id="thorough_review_v1",
        label="充分查证",
        description="返回更多候选证据，适合争议主张或生成前的完整检查。",
        top_k=12,
        tradeoff="召回更广，但噪声和人工复核成本更高。",
    ),
    "document_generation_v1": RetrievalProfile(
        id="document_generation_v1",
        label="文档生成内部检索",
        description="文档生成时每条显式查询使用的内部基线配置。",
        top_k=5,
        tradeoff="用于构建受控 Evidence Package，不代表全局最佳配置。",
    ),
}


def get_retrieval_profile(profile_id: str) -> RetrievalProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown retrieval profile: {profile_id}") from exc


def list_retrieval_profiles() -> list[dict[str, Any]]:
    return [profile.as_dict() for profile in _PROFILES.values()]
