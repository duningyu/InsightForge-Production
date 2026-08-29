# InsightForge 3.0 Claim Boundary

## 1. What an engineering result can prove

A passing automated test can establish a defined software behavior under the test fixture, for example:

- project scope blocks a cross-project evidence link;
- an exact evidence span must exist in the stored chunk;
- a source archive makes a dependent artifact stale;
- an accepted Change Proposal creates a new immutable Snapshot;
- a stale document blocks Handoff.

It cannot establish that users prefer the workflow, finish faster, produce better product decisions, retain, pay, or outperform another product.

## 2. Source types and allowed interpretation

| Source type | Can support | Cannot automatically prove |
|---|---|---|
| `real_user_research` | statements within the recorded sample/context | population-wide demand, willingness to pay, product-market fit |
| `public_source` | traceable public facts/context within scope/date | the current target user's exact problem or behavior |
| `implementation_evidence` | implementation/data/technical feasibility | user need, user value, market demand |
| `simulated_research` | demonstration/test scenario only | any real-user validation status |
| `user_input` | project-owner intent/constraint | market truth |
| `model_hypothesis` | candidate hypothesis to verify | evidence |

`simulated_research`, `user_input`, and `model_hypothesis` do not upgrade project Claims through the Evidence engine. `implementation_evidence` is admissible only for `feasibility`.

## 3. Provenance is not verification

A Claim has separate fields:

```text
provenance            verification_status
-----------           -------------------
user_input            unverified
model_hypothesis      limited_support
...                   supported/conflict/contradicted/stale
```

Confirming an IdeaBrief or editing project intent does not turn it into market evidence.

## 4. Supported does not mean universal truth

`verification_status=supported` means the currently linked admissible evidence satisfies the deterministic support rule for that Claim in its recorded scope. It does not authorize language such as “the market proves...” or “all users need...”. Sample scope remains part of the Claim interpretation.

## 5. Evidence relation is constrained

A persisted project evidence relation must satisfy all of the following:

- Claim belongs to the current project and is active;
- source/chunk pair exists in the same project;
- source is active;
- source type is admissible for the Claim type;
- evidence is not stale;
- quoted `evidence_span` exists in the stored chunk after newline normalization/outer trim;
- if a retrieval run is supplied, the source/chunk must be an actual hit from that project run.

The LLM can propose a relation but cannot bypass these checks.

## 6. Historical artifact boundary

A source or Claim change can change `artifact_health`; it cannot rewrite old Snapshot or document content. Historical artifacts preserve what was confirmed at that time. Current usability can become `needs_review`, `stale_evidence`, or `superseded`.

## 7. User confirmation boundary

The single-user UI uses **Confirm this version**. This is a user Gate establishing which version is current for handoff. It is not an enterprise multi-role approval process.

## 8. Runtime boundary

`deterministic_demo` proves only frozen workflow contracts. `llm_structured` is a live semantic adapter and requires a separately frozen product-evaluation protocol before any semantic-quality claim.

## 9. Explicit claims not supported by this release

Do not claim:

- proven five-minute first value;
- validated real-user productivity improvement or retention;
- superiority to ChatGPT/ChatPRD/Productboard/Notion;
- autonomous PM replacement;
- GraphRAG/knowledge graph innovation;
- multi-agent reasoning as a shipped core;
- enterprise-grade access control/security/SLA;
- production remote MCP integration;
- market validation from synthetic examples or engineering fixtures.
