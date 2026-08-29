# InsightForge — User Feedback and Iteration Record

## Evidence boundary

This document records product feedback that motivated the redesign and how the implementation responded. Feedback is qualitative product evidence. It does **not** establish statistically validated user value, retention, conversion, or market demand.

Synthetic examples remain synthetic; implementation tests remain implementation evidence.

## 1. 2.0.6 feedback themes

### Ordinary-user perspective

The 2.0.6 product exposed many reasonable capabilities at the same level: product coach, Canvas, three implementation proposals, source governance, RAG, PRD/TechDoc, Claim ledger, confirmation/approval, recycle bin, and AI Coding handoff. The resulting problem was not missing functionality but an unclear primary value proposition.

The most important feedback was:

1. **Core value was difficult to state.** The product looked like a complete product-development workbench rather than something a user “must use” for one first job.
2. **Time to first value was too long.** Creating a project, answering guidance, confirming Canvas, adding evidence, choosing a solution, generating/validating documents, and confirming versions came before the user saw a compact product result.
3. **The three solutions were not actually about the user's Idea.** The old choices (“guided product coach”, “evidence-first workspace”, “single-task lightweight MVP”) were forms of InsightForge itself, not distinct domain mechanisms for the user's problem.
4. **Idea implementation paths were generic.** “narrow the scenario → prototype → trial → review” could fit almost any project; it lacked concrete pages, fields, logic, data, technical composition, implementation slices, acceptance cases, and major unknowns.
5. **Source impact was not visible enough.** Users could see what was uploaded and cited but could not directly answer “which conclusion did this source support or weaken, which recommendation changed, and which document is now stale?”
6. **State was too heavy.** `draft`, `passed`, confirmation/approval, evidence gaps, handoff readiness, and version states competed for attention instead of one clear “what should I do next, and why?”
7. **There was no strong results surface.** Users needed one page summarizing target user/problem, chosen solution, MVP, risks/evidence state, and next action for discussion, screenshot, portfolio, or handoff.

### Product-manager interview perspective

The parallel concern was that feature count and engineering complexity do not prove product effectiveness. Likely review questions include:

- Who is the primary target user?
- Why not use ChatGPT/ChatPRD/Notion/Dify for this task?
- Does the evidence system actually reduce unsupported conclusions?
- What changes after a source is added or removed?
- Is “approval” a real multi-role workflow or just the same user clicking another button?
- Which outcomes have real-user data and which are only implementation demonstrations?

## 2. Product decision for 3.0

Primary persona was narrowed to:

> AI product job seekers + junior/transitioning PMs who already have a rough Idea but do not yet know which product solution/MVP to build, which assumptions are real versus guessed, or how to make the result defensible for implementation and portfolio discussion.

Independent developers become secondary users. Mature PMs may use advanced evidence/history detail but do not drive default IA.

The approved architecture is **Quick Value → Evidence Depth**.

## 3. Main 3.0 responses

### First value before governance

```text
Idea → IdeaBrief → 2–3 domain solutions → user choice → Project Snapshot
```

Canvas/source/RAG/document governance no longer blocks the first formal result.

### Domain solutions, not platform shapes

For a convenience-store replenishment Idea, the frozen example compares mechanisms such as:

- inventory-threshold rule reminder;
- sales-based forecast reminder;
- forecast + human confirmation.

The solution contract includes user flow, MVP pages/features, input/output fields, decision logic, data requirements, technical components, two-week slices, acceptance cases, risk, and unknowns.

### Evidence changes decisions visibly

The new model is:

```text
Source → Project Claim → Decision dependency → Artifact impact → Change Proposal
```

A source can support, contradict, or contextualize a Claim. Material changes are explained and require user confirmation before a new Snapshot is created.

### Results page

`Project Snapshot` is the primary result surface. It represents “what the project currently is,” while system-level objects such as RAG configuration and raw Claim IDs move into detail views.

### One next-best action

The system derives the highest-risk unresolved Claim rather than showing every possible workflow status as an equal CTA.

### Confirmation, not organization-level approval

The user action is renamed **Confirm this version**. It establishes a single-user source of truth for export/handoff; no multi-role enterprise approval capability is claimed.

## 4. Version evolution

| Version | Primary shape | Main issue / change | Status |
|---|---|---|---|
| 1.x | Evidence-oriented technical workspace | strong provenance/version controls, high technical burden | historical |
| 2.0.x | Guided Evidence Workspace | reduced onboarding burden but still long before first value; solutions remained platform-centric | superseded |
| 2.0.6 | stable redesign baseline | untouched baseline passed 99 pytest tests; product-semantic limitations remained | migration baseline |
| 3.0.0 | Quick Value → Evidence Depth | domain solution comparison + Snapshot first; Evidence becomes visible decision-impact layer | current implementation |

## 5. What remains unvalidated

Engineering completion does not answer the following product questions:

- Do target users reach a useful first Snapshot within the intended time window?
- Are the generated solution alternatives more useful than a normal ChatGPT conversation?
- Do users understand Claim/evidence states without training?
- Does evidence impact reduce unsupported product assertions or rework?
- Do users return to update the project after new evidence?
- Does the Handoff reduce developer clarification/rework?

These require separately designed real-user tests with frozen tasks, success criteria, and honest reporting of failures. No answer is inferred from the 3.0 automated test suite.

## 6. Historical 2.0 qualitative feedback record retained for audit

The redesign did not erase the earlier product-learning record. In the 2.0 line, the evidence was explicitly described as **一次定性产品经理反馈** and **不构成市场验证**. Representative friction included **约束不知道怎么填**, **RAG 配置用途不清楚**, an **AI Coding 交接只有名义接口** concern in an earlier stage, and the perception that parts of the evidence/retrieval path were a **黑箱**.

That record spans the transition from **v1.1.0** to **v2.0.0** and then 2.0.6. These phrases are retained as historical feedback evidence only; they are not claims that every 3.0 user experiences the same issue, nor proof that 3.0 has solved them in real-user outcomes.
