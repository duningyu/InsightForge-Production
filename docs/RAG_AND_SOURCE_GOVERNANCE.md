# RAG, Provenance and Source Governance

## Retrieval profiles

| ID | Top-K | User-facing purpose |
|---|---:|---|
| `quick_explore_v1` | 4 | Quickly check whether the source direction is useful |
| `balanced_traceable_v1` | 8 | Default balance between recall and review burden |
| `thorough_review_v1` | 12 | Wider review for disputed or high-impact claims |
| `document_generation_v1` | 5/query | Internal Evidence Package construction |

All use the current local baseline:

```text
hybrid = 0.55 * BM25 + 0.30 * TF-IDF cosine + 0.15 * authority
```

The configuration is explicitly labelled `manual_baseline_not_frozen_best`. It is traceable, but the product不得声称参数最优. A separate frozen query/evidence set is required before recommending a best profile.

## What a retrieval run records

- run ID and project ID;
- query and purpose;
- profile ID and effective Top-K;
- whether Top-K came from the profile or an explicit override;
- BM25/cosine/authority weights;
- source-type filter;
- candidate and returned counts;
- ranked hit scores;
- actor and timestamp;
- selection basis and validation status.

The UI answers “为什么使用当前检索档位” and shows the trade-off, rather than presenting Top-K as an unexplained expert setting.

## Relevance before authority

Project scope and optional source types are filtered in SQL. Authority only re-ranks lexically related chunks. A high-authority chunk with no BM25/cosine signal is excluded.

## Novice source categories

Users can select plain-language categories such as real interview, official page, public report, personal project input, simulation, model output, and implementation evidence. The guidance layer maps them to the internal taxonomy and explains:

- what the source can support;
- what it cannot support;
- recommended authority level;
- why that recommendation was made;
- whether confirmation is still required.

## Internal source taxonomy

- `real_user_research`: genuine user research with provenance and sample limits.
- `simulated_research`: artificial samples; never a real-user conclusion.
- `public_source`: official/public pages and reports; can support published facts only.
- `user_input`: project-owner goals, decisions, and constraints.
- `model_hypothesis`: unverified model output.
- `implementation_evidence`: code, tests, runtime, README, or API evidence; proves implementation state only.

## Provenance contract

Sources can store URL, publisher, published/captured time, authority label/basis, status, metadata, filename, SHA-256, source ID, and chunk IDs. A citation is a stable `[source:...#chunk:...]` pair.

## Claim-Evidence Ledger

Claims are persisted as:

- `user_confirmed` — direct approved Canvas/user statements;
- `source_backed` — linked to valid project chunks;
- `model_suggestion` — locally disclosed recommendation;
- `unresolved` — insufficient evidence or conservative LLM import.

The ledger improves traceability but does not establish semantic truth automatically. Human review remains required for material claims.

## Evaluation protocol

A serious RAG evaluation should predefine and freeze:

- query set;
- expected source/chunk labels;
- profile candidates;
- validation-only selection;
- final frozen report.

Report Recall@K, Citation Precision, Claim Support Rate, Unsupported Claim Rate, source-type disclosure, project isolation failures, latency, candidate count, and results by source type. Repeatedly changing profiles based on the frozen report is prohibited.
