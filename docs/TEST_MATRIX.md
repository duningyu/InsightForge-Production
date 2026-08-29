# InsightForge 3.0 Test Matrix

Engineering tests verify software contracts only. They do not measure user-product effectiveness.

## Release baseline

Untouched InsightForge 2.0.6 baseline before 3.0 work:

```text
99 passed
```

## 3.0 areas

| Area | Representative tests | Contract |
|---|---|---|
| release identity | `test_v3_release_identity.py` | runtime/package/static/report version truth |
| additive schema | `test_v3_schema_migration.py` | old DB upgrade, new tables/columns, idempotence |
| Quick Start | `test_v3_quick_start.py` | IdeaBrief provenance, clarification, no Guided bootstrap |
| solutions | `test_v3_solution_design.py`, `test_v3_solution_api.py` | 2–3 domain solutions, diversity, no forced AI |
| Snapshot transaction | `test_v3_snapshot_transaction.py` | human Gate, atomic Decision/Claims/Snapshot/Canvas projection |
| Evidence policy | `test_v3_project_claim_evidence.py` | source policy, exact span, scope/retrieval trace, status rules |
| Change Proposal | `test_v3_change_proposals.py` | material impact, stale proposal check, immutable versions |
| source lifecycle | `test_v3_source_lifecycle.py` | archive/restore propagation, SHA/span revalidation, rollback |
| document health | `test_v3_document_health.py` | Snapshot-bound generation, dependencies, health/confirmation |
| handoff/tools | `test_v3_handoff_and_tools.py` | healthy-current fail-closed readiness, L0/L1/L2 gates |
| five-module UI | `test_v3_ui_quick_value_contract.py`, `test_v3_ui_evidence_documents_handoff.py` | exact top IA, evidence/document/handoff copy and responsive shell |
| legacy migration | `test_v3_legacy_migration.py` | legacy Snapshot label, no invented evidence/validation, deprecated Guide |
| frozen acceptance | `test_v3_golden_cases.py`, `test_v3_end_to_end.py` | ten approved engineering cases and full P0 chain |

## Ten frozen 3.0 engineering cases

`tests/fixtures/v3_golden_cases.json` records structural expected outcomes for:

1. convenience-store replenishment;
2. non-AI workflow where all-AI overengineering is rejected;
3. real ambiguity requiring one clarification;
4. only two materially different valid solutions;
5. conflicting independent real-user evidence;
6. simulated research cannot upgrade project Claim validation;
7. implementation evidence supports feasibility but not user value;
8. source archive causes stale artifact health;
9. cross-project evidence attack is blocked;
10. legacy 2.0.6 migration is conservative and idempotent.

The fixture stores structural outcomes and exact frozen spans; it is not a benchmark for arbitrary LLM prose.

## End-to-end acceptance path

The convenience-store test executes:

```text
quick-start
→ confirm IdeaBrief
→ generate domain solutions
→ confirm rule-based solution
→ Snapshot v1
→ add real-user evidence
→ exact-span evidence analysis
→ contradicted critical Claim
→ material Change Proposal
→ user accepts
→ Snapshot v2
→ generate/confirm PRD + TechDoc
→ archive cited public source
→ documents stale_evidence
→ handoff readiness false
```

It also proves Snapshot v1's content hash is unchanged.

## Critical engineering evidence

The release verification must report:

- full legacy + 3.0 test result;
- targeted 3.0 integrity result;
- migration idempotency;
- cross-project evidence leakage failures = 0;
- invalid evidence-span proposals blocked;
- historical artifact mutation failures = 0;
- silent runtime fallback count = 0;
- version-truth mismatch count = 0.

## Required commands

```bash
pytest -q
pytest tests/test_v3_schema_migration.py \
       tests/test_v3_snapshot_transaction.py \
       tests/test_v3_project_claim_evidence.py \
       tests/test_v3_change_proposals.py \
       tests/test_v3_source_lifecycle.py \
       tests/test_v3_document_health.py \
       tests/test_v3_handoff_and_tools.py \
       tests/test_v3_legacy_migration.py \
       tests/test_v3_end_to_end.py -q
python -m compileall -q app tests
node --check app/static/app.js
```

Exact observed counts belong in `VERIFICATION_REPORT.md`, not this design matrix, so this file does not become stale when a release-contract test is added.
