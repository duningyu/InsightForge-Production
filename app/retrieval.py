from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

_WORD_RE = re.compile(r"[a-zA-Z0-9_+#.-]+|[\u3400-\u4dbf\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text.lower()):
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", raw):
            tokens.append(raw)
            tokens.extend(raw)
            tokens.extend(raw[index : index + 2] for index in range(len(raw) - 1))
        else:
            tokens.append(raw)
    return [token for token in tokens if token.strip()]


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [1.0 if value > 0 else 0.0 for value in values]
    return [(value - low) / (high - low) for value in values]


def _bm25_scores(query_tokens: list[str], document_tokens: list[list[str]]) -> list[float]:
    if not query_tokens:
        return [0.0] * len(document_tokens)
    document_count = len(document_tokens)
    if document_count == 0:
        return []
    avg_length = sum(len(tokens) for tokens in document_tokens) / document_count
    doc_frequencies = Counter()
    for tokens in document_tokens:
        doc_frequencies.update(set(tokens))
    query_counts = Counter(query_tokens)
    k1, b = 1.5, 0.75
    scores: list[float] = []
    for tokens in document_tokens:
        frequencies = Counter(tokens)
        length = max(len(tokens), 1)
        score = 0.0
        for token, query_frequency in query_counts.items():
            frequency = frequencies.get(token, 0)
            if frequency == 0:
                continue
            df = doc_frequencies[token]
            idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * length / max(avg_length, 1.0))
            score += idf * (frequency * (k1 + 1) / denominator) * (1 + math.log(query_frequency))
        scores.append(score)
    return scores


def _cosine_scores(query_tokens: list[str], document_tokens: list[list[str]]) -> list[float]:
    if not query_tokens:
        return [0.0] * len(document_tokens)
    document_count = len(document_tokens)
    if document_count == 0:
        return []
    doc_frequencies = Counter()
    for tokens in document_tokens:
        doc_frequencies.update(set(tokens))
    query_counts = Counter(query_tokens)
    query_vector: dict[str, float] = {}
    for token, count in query_counts.items():
        idf = math.log((document_count + 1) / (doc_frequencies.get(token, 0) + 1)) + 1
        query_vector[token] = (1 + math.log(count)) * idf
    query_norm = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0

    scores: list[float] = []
    for tokens in document_tokens:
        counts = Counter(tokens)
        dot = 0.0
        norm_sq = 0.0
        for token, count in counts.items():
            idf = math.log((document_count + 1) / (doc_frequencies.get(token, 0) + 1)) + 1
            value = (1 + math.log(count)) * idf
            norm_sq += value * value
            dot += value * query_vector.get(token, 0.0)
        scores.append(dot / (query_norm * (math.sqrt(norm_sq) or 1.0)))
    return scores


class HybridRetriever:
    def __init__(
        self,
        bm25_weight: float = 0.55,
        cosine_weight: float = 0.30,
        authority_weight: float = 0.15,
    ):
        if not math.isclose(bm25_weight + cosine_weight + authority_weight, 1.0, abs_tol=1e-6):
            raise ValueError("retrieval weights must sum to 1")
        self.bm25_weight = bm25_weight
        self.cosine_weight = cosine_weight
        self.authority_weight = authority_weight

    def search(
        self,
        query: str,
        documents: Iterable[dict[str, Any]],
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        rows = [dict(document) for document in documents]
        if not rows:
            return []
        query_tokens = tokenize(query)
        document_tokens = [tokenize(str(row.get("content", ""))) for row in rows]
        bm25 = _normalize(_bm25_scores(query_tokens, document_tokens))
        cosine = _normalize(_cosine_scores(query_tokens, document_tokens))
        ranked: list[dict[str, Any]] = []
        for row, bm25_score, cosine_score in zip(rows, bm25, cosine, strict=True):
            authority = min(1.0, max(0.0, float(row.get("authority", 0.0))))
            hybrid = (
                self.bm25_weight * bm25_score
                + self.cosine_weight * cosine_score
                + self.authority_weight * authority
            )
            lexical_signal = bm25_score > 0 or cosine_score > 0
            if not lexical_signal:
                continue
            ranked.append(
                {
                    **row,
                    "bm25_score": round(bm25_score, 6),
                    "cosine_score": round(cosine_score, 6),
                    "authority_score": round(authority, 6),
                    "hybrid_score": round(hybrid, 6),
                }
            )
        ranked.sort(
            key=lambda item: (
                -item["hybrid_score"],
                -item["authority_score"],
                str(item.get("chunk_id", "")),
            )
        )
        for rank, item in enumerate(ranked[:top_k], start=1):
            item["rank"] = rank
        return ranked[:top_k]
