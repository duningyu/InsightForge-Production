# R1-R4 RED evidence — 2026-09-12

Baseline: `dbc27d814b8aceaee54a0a46384589e7e4db555c`, branch `deploy/railway-stage-b`.
Tests were added and executed before production changes. Test setup/signature mistakes were corrected before the valid baseline run below; those earlier setup failures are not counted as regression evidence.

## Baseline RED

```powershell
py -3.12 -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_whole_branch_fixes.py
node tests/whole_branch_fix_harness.js
```

Observed pytest summary: **113 failed, 4 passed in 51.31s**, exit 1; `EXTERNAL_CONNECTION_ATTEMPTS=0`.
Observed JavaScript summary: **98 failed, 19 passed**, exit 1.
These are recorded summaries of executed runs, not a claim that an unmodified baseline checkout contains the new tests.

Representative expected failures:

- R1: `DID NOT RAISE StructuredOutputContractError` for synthetic provider envelopes embedded in allowed scalar/list/disclosure values; corrupted stored public responses returned HTTP 200 instead of 503. Failure metadata retained arbitrary text. Generation, document persistence/replay and async public replay also accepted raw values.
- R2: the actual frontend rejected otherwise valid partial AI references during generation/load/retry. Controls kept all four Action Card lists mandatory and rejected completely empty reference payloads.
- R3: generated selected-B PRD/TechDoc content failed the actual frontend inherited-snapshot adapter, including distinct inherited summary/core idea and selected MVP pages.
- R4: honest explicit exclusions were rejected; positive added-scope controls were retained.

## Additional diff-review RED, before corresponding fixes

The document boundary selection (`-k 'replay_citation or lifecycle_api or draft_load'`) produced **2 failed, 1 passed, 117 deselected in 8.77s**, with zero external connection attempts. Replay citations and lifecycle public reads still exposed injected synthetic raw values; draft loading was the passing control.

An added JavaScript check for a positive commitment hidden in a non-goal heading (`## 非目标 支持支付`) produced **117 passed, 1 failed**. The subsequent fix retained exclusion support but checked positive heading content.

## Isolation and interpretation

The committed local runner removes provider/search configuration, disables real-provider mode, blocks non-loopback socket connections, and fails on attempted external connections. Payloads contain synthetic sentinel text only. JavaScript uses a fake DOM and mocked fetch around the actual `app.js`; it is not browser evidence for R5. Final GREEN commands and results are recorded in `r1-r4-fix-report.md`.
