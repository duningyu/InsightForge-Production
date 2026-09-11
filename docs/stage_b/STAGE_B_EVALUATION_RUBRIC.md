# Stage B Evaluation Rubric

Score each dimension from 1 (poor) to 5 (strong). Use blind labels `Output A` and `Output B` before revealing whether the output is InsightForge or the direct baseline.

## AI guidance

| Dimension | Question |
| --- | --- |
| Context fidelity | Does it understand the raw idea without inventing context? |
| Specificity | Are recommendations concrete rather than generic? |
| Novel value | Does it add useful insight instead of paraphrasing? |
| Decision usefulness | Does it support a product trade-off? |
| Uncertainty honesty | Are unknowns marked as assumptions or validation items? |
| Actionability | Is the next action clear? |

Critical fail: fabricated research, market facts, competitor facts, existing evidence, or a material misunderstanding of the idea.

## Solutions

| Dimension | Question |
| --- | --- |
| Context fit | Do the options address this idea and user? |
| Differentiation | Can a reviewer state one distinct trade-off per option? |
| Trade-off quality | Are selection and rejection reasons explicit? |
| MVP realism | Is the first version implementable? |
| Decision support | Can the user choose based on the differences? |
| Guidance consistency | Do options inherit the useful guidance? |

Hard gate: solution differentiation must be at least 4/5 per idea.

## Documents and handoff

For the selected solution, mark each inheritance item `PASS` or `FAIL`:

- target user comes from the real context;
- core problem remains consistent;
- selected solution is the one in PRD and TechDoc;
- MVP scope and key trade-offs are preserved;
- assumptions remain validation items, not facts;
- TechDoc architecture, modules, tasks, and acceptance cases match PRD;
- Handoff references the exact confirmed PRD and TechDoc versions;
- a developer can identify the first implementation step from the Handoff.

Score PRD, TechDoc, and Handoff quality 1–5 for structure, specificity, executability, consistency, scope control, and non-template content.

## Minimum decision gate

- Context fidelity: every idea at least 4/5;
- uncertainty honesty: no critical fabrication;
- solution differentiation: every idea at least 4/5;
- decision usefulness and actionability: mean at least 4/5;
- InsightForge is at least as good as the direct baseline on at least 2 of 3 ideas.

If these conditions are not met, report the failure honestly; do not tune prompts mid-batch or adjust scores to pass.
