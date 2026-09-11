# Stage B Runbook

This runbook stops before real-provider smoke. It prepares the isolated environment and tells the operator exactly where the boundary is.

## 1. Create an isolated target

Create a separate Railway Service or Environment named `insightforge-stage-b` from the Stage B branch. Use a new Volume mounted at `/app/data`; never attach the Stage A, beta, or real-user Volume. Keep one replica and `/api/health`.

The Stage A Service must remain unchanged and continue using its synthetic configuration.

## 2. Configure non-secret variables

Set these only on the Stage B Service:

```text
INSIGHTFORGE_SAFE_FIXTURE_MODE=false
REAL_PROVIDER_STAGE_B=true
INSIGHTFORGE_ACCOUNTS_ENABLED=false
BETA_PARTICIPANT_ID=railway_stage_b
INSIGHTFORGE_DATA_ROOT=/app/data
INSIGHTFORGE_STAGE_B_TRANSPORT_BUDGET=12
MANAGED_QWEN_MODEL=qwen3.7-flash
```

Keep Search unconfigured. Do not set `PORT=8000`; Railway injects `PORT`.

## 3. Configure the secret manually

After the Service is isolated, enter the Bailian key manually in that Service’s Variables using the existing adapter variable (`MANAGED_BAILIAN_API_KEY`, or the already supported equivalent). Do not send the key in chat and do not place it in Git, images, logs, screenshots, or artifacts.

Before the first request, verify the Stage A Service has no inherited provider key. If the Railway UI would make the key project-wide, stop and redesign the isolation; do not proceed.

## 4. First smoke only

Run one non-user synthetic provider prompt with provider `bailian` and model `qwen3.7-flash`. Verify:

- one dispatch and one transport;
- success response and schema validation;
- usage/latency trace;
- no automatic retry;
- no key or prompt in ordinary logs;
- Stage A and beta environments unchanged.

Stop after this smoke. Do not run `idea_A/B/C` until the operator reviews the trace.

## 5. Real idea batch

Only after smoke review, collect three user-supplied raw ideas. Do not rewrite them before recording. Run A, then checkpoint; run B, then checkpoint; run C, then checkpoint. The normal budget is 9 transports for 3 ideas, with the hard ceiling of 12 including manually authorized retries.

Do not retry silently. Record each retry as a new logical attempt with its ordinal and reason.

## 6. Private artifacts

Store full prompts, responses, and scorecards outside the repository in a private evaluation directory. Commit only empty schemas/templates and the rubric. Public receipts use `idea_A`, `idea_B`, `idea_C` and redacted IDs only.

## 7. Stop conditions

Stop immediately on wrong participant, accounts enabled, safe fixture enabled, unexpected provider dispatch, secret exposure, budget exhaustion, fabricated evidence, or a source/config drift. Never use Stage A synthetic projects as Stage B quality evidence.
