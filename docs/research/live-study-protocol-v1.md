# Live study protocol — production_pipeline_paired_v1

**Status:** DRAFT — methodology frozen, live admission NOT GRANTED
**External human approval verified:** `false`
**Live study status:** NOT ADMITTED FOR LIVE STUDY

## Study identity

| Field | Value |
|-------|-------|
| Protocol ID | `production_pipeline_paired_v1` |
| Experiment scope | `production_pipeline_paired_v1` |
| Study version | `v1` |
| Date drafted | 2026-10-02 |
| Repository revision at draft | `19843870e48c45a4bdff55a9c84553f4eecadb74` |
| Execution mode (implemented) | `offline_fixture` |

This document freezes the *methodology*. It does not authorize, schedule, or
qualify a live run. Live admission additionally requires human-reviewed
fixtures, a chosen target provider/model, provider and spending authorization,
and external human approval — none of which are recorded in this repository.

## Research question

Does PromptPilot's structured prompt analysis, clarification, project memory,
context retrieval, context assembly, and optimized prompt generation improve
response quality compared with sending the original task directly to the same
target model?

## Scope separation

`production_pipeline_paired_v1` is a distinct experiment scope from the older
`benchmark_infrastructure_smoke_test`. The smoke test validates infrastructure
wiring only and MUST NOT be modified to satisfy this protocol. Any result
labelled `benchmark_infrastructure_smoke_test` is not evidence for the research
question above.

## Dataset

* **Name:** `promptpilot-experimental-v1`
* **Canonical SHA-256:** `8b7aca964ffae59151a3c8c24a3412823b7d96ff7739d66e9b79ab71648cc53d`
* **Tasks:** 8 — the dataset is used **unchanged**. No task is added, removed,
  edited, or reworded.

| Task ID | Category | Human fixture status |
|---------|----------|----------------------|
| writing-email-001 | writing | PENDING HUMAN REVIEW |
| summarization-policy-001 | summarization | PENDING HUMAN REVIEW |
| qa-geography-001 | question_answering | PENDING HUMAN REVIEW |
| extraction-invoice-001 | extraction | PENDING HUMAN REVIEW |
| planning-launch-001 | planning | PENDING HUMAN REVIEW |
| technical-api-001 | technical_software | PENDING HUMAN REVIEW |
| business-analysis-001 | business_professional | PENDING HUMAN REVIEW |
| research-information-001 | research_information | PENDING HUMAN REVIEW |

### Fixture admission

Each of the 8 tasks requires a human-authored fixture containing frozen document
bytes (SHA-256 verified), clarification answers bound to gap keys, reviewer
identity, review timestamp, and a provenance/consent evidence reference, with
attestation version `v1` and `test_only: false`.

No checked-in synthetic fixture is live-eligible. All existing fixtures in this
repository are test-only and remain test-only; they MUST NOT become live
fixtures, and they MUST NOT be used as live responses.

A task is ADMITTED iff its `FixtureManifest` passes `admit_live_manifest` against
the frozen dataset, reviewer identity and timestamp are externally verified, the
provenance/consent reference is authenticated, and `test_only` is `false`.
Otherwise the task is REJECTED, or NEEDS HUMAN REVIEW if not yet evaluated.

## Conditions

### Baseline (control)

Exactly:

```
Original Task -> Target Model -> Response
```

The baseline receives **only** the original task text. It receives no analysis,
no clarification answers, no project memory, no treatment documents or
retrieved context, no assembled context, and no optimized prompt. The offline
orchestrator enforces this by executing the baseline with the source message
content and failing the unit if the executed prompt differs from the original
task.

### Treatment (PromptPilot)

```
Original Task
  -> Prompt Analysis
  -> Clarification (capped)
  -> Project Memory
  -> Context Retrieval
  -> Context Assembly
  -> Optimized Prompt
  -> Same Target Model
  -> Response
```

### Equivalence requirement

Both conditions MUST use the **same** provider, the **same** model, the **same**
frozen generation parameters, the same source task, and the same task/repetition
identity. Any difference invalidates the pair.

## Repetitions and condition order

**R = 3 repetitions per task.** The order is fixed and persisted with each pair:

| Repetition | Execution order |
|------------|-----------------|
| 1 | baseline -> PromptPilot |
| 2 | PromptPilot -> baseline |
| 3 | baseline -> PromptPilot |

Order is persisted per unit record so that the executed order can be audited
after the fact. A unit whose order cannot be recovered from evidence is invalid.

## Question policy

* **Question cap Q = 2** per task/repetition. No question generation occurs
  after the cap is reached.
* Question generation is AI-backed for each unresolved gap, prioritized by gap
  severity and dimension weight.
* Questions are answered only from the frozen fixture answers bound to gap keys.

### Unresolved-gap and unanswered-question policy (FROZEN)

* **Unmatched gap (no matching fixture answer): `skip`.**
* **Unanswered question (cannot be answered): `skip`.**

`skip` means: do not answer, do not fabricate, do not infer, and do not invent a
placeholder. The question is recorded as explicitly unresolved and the unit does
not become a complete pair.

Explicit unresolved records are always written:

* `unanswered_questions` — one record per question presented without an answer,
  including question id, gap id, question text, dimension, resolution (`skip`),
  and reason.
* `unmatched_gaps` — one record per gap with no matching fixture answer.
* `unresolved_gaps` — one record per gap still open when clarification ends
  (cap reached), marked `resolution: unanswered`.

A missing answer is never converted into an answered state, and an unanswered
question is never silently counted as answered.

## Clarification termination

Clarification stops when any of the following holds:

1. the question cap is reached;
2. all gaps are resolved and no unresolved gaps remain;
3. the unmatched-gap policy triggers `stop` (not used in the frozen protocol —
   the frozen value is `skip`);
4. a question-generation fallback triggers the fallback policy.

## Fallback policy (FROZEN)

**Primary full-pipeline fallback admission: `reject`.**

| Failure point | Classification | Effect on primary result set |
|---------------|----------------|------------------------------|
| Analysis provider fails | `reject` | unit is partial; excluded from primary |
| AI question generation fails | `reject` | unit is partial; excluded from primary |
| Optimized prompt generation fails | `reject` | invalid pair; excluded |
| Document ingestion fails | `reject` | invalid pair; excluded |
| Target model call fails | `reject` | invalid pair; excluded; other condition's response retained as evidence |
| LLM-judge evaluation fails | `reject` | invalid pair; excluded |

Fallback-containing runs MAY be retained **diagnostically only**. A fallback run
is never relabelled, never reclassified, and never merged into the primary
analysis stratum. There is no automatic fallback to a heuristic evaluation.

## Evaluation method (FROZEN)

* **Primary evaluator:** `llm_judge`
* **Secondary evaluator:** none. There is no secondary evaluation method in this
  protocol.
* **Rubric:** `v1` (frozen)

| Dimension | Weight |
|-----------|--------|
| relevance | 25 |
| completeness | 20 |
| instruction_following | 20 |
| contextual_grounding | 20 |
| clarity | 15 |

Backend-owned weighted aggregation is unchanged: the weighted sum of the five
dimension scores yields a 0–100 scale, and the overall winner is the sign of the
delta. No dimension weight is changed and no alternative aggregation is used.

Invalid judge output is a `reject` case (see fallback policy). It does not
silently degrade to a heuristic score.

## Neutral A/B judge protocol (FROZEN)

The judge MUST receive only neutral material:

* the original task;
* the shared requirements;
* the shared constraints;
* the evidence legitimately available to A;
* the evidence legitimately available to B;
* Response A;
* Response B.

The judge MUST distinguish shared evidence, condition-specific evidence, and
generated assumptions. The judge MUST NOT invent requirements, and MUST NOT
penalize a response for information it could not access. Evidence that is
legitimately available to only one condition is recorded as belonging to that
condition only; it is never presented as shared.

**Blinding requirements:**

* The judge prompt MUST NOT contain the identity of either condition. The words
  `baseline` and `PromptPilot` MUST NOT appear in the judge prompt or the judge
  payload.
* Responses are presented under neutral labels A and B.
* The mapping from A/B to the actual conditions is stored **separately** from the
  judge payload, in the evaluation metadata for audit, and is never sent to the
  judge.

## Target model

* **Provider:** PENDING HUMAN DECISION (must be OpenRouter-compatible)
* **Model:** PENDING HUMAN DECISION

### Frozen generation parameters

| Parameter | Value |
|-----------|-------|
| temperature | 0 |
| top_p | 1.0 |
| stop | `[]` |
| presence_penalty | 0 |
| frequency_penalty | 0 |
| seed | `null` |

### Pending parameters (no value is invented here)

| Parameter | Status |
|-----------|--------|
| provider | PENDING HUMAN DECISION |
| model | PENDING HUMAN DECISION |
| max_tokens | PENDING HUMAN DECISION |
| timeout | PENDING HUMAN DECISION |

Only parameters actually sent to the provider are recorded. No seed is invented.

## Call budget (FROZEN)

Given F = 8 admitted fixtures, R = 3, Q = 2, J = 1, U = F x R = 24:

| Role | Calls |
|------|-------|
| analysis | 24 |
| question_generation | 48 |
| prompt_generation | 24 |
| target_execution | 48 |
| judge | 24 |
| **Total** | **168** |

There is no hidden safety budget, no automatic target retry, and no silent
increase of the ceiling. The ledger enforces the exact per-role and total
ceilings. Any further provider call is a protocol violation.

## Analysis strata (FROZEN)

The primary analysis is reported over exactly two strata:

1. **Overall** — all admitted pairs.
2. **Task category** — the dataset's 8 categories.

No primary stratum is added or removed after results are seen. Any additional or
post-hoc analysis is **exploratory** and MUST be labelled as such, and MUST NOT
be presented as a primary confirmatory result.

## Failure and exclusion codes

| Failure type | Predefined code | Pair disposition |
|--------------|----------------|------------------|
| Provider timeout | `timeout` | invalid pair |
| Rate limit | `rate_limit` | invalid pair |
| Invalid provider response | `invalid_response` | invalid pair |
| Missing fixture | `missing_fixture` | invalid pair |
| Unmatched gap (no fixture answer) | `unmatched_gap` | skip; explicit unresolved record |
| Unanswered question | `unanswered_question` | skip; explicit unresolved record |
| Question cap reached | `question_cap_reached` | partial unit |
| Analysis / question fallback | `*_fallback_rejected` | partial unit |
| Prompt generation failure | `prompt_generation_failed` | invalid pair |
| Evaluation failure | `evaluation_failed` | invalid pair |
| Budget exhausted | `budget_exhausted` | failed experiment |

No silent deletion of bad outcomes. Every exclusion carries a predefined reason
code.

## Data retention

Retained per attempt, credential-free:

* original task, requirements, constraints, allowed context
* answers, project memory used, assembled context, with omissions recorded
* optimized prompt (PromptVersion id), baseline prompt
* baseline response, PromptPilot response
* provider, model, generation parameters actually sent
* ModelRun, PromptVersion, and Evaluation ids
* evaluation scores, request hashes, dataset hash, repository SHA
* timestamps, and failures recorded by safe error type/code
* explicit unresolved records for skipped and unanswered questions

API credentials are never stored. Known credentials and authorization headers
are redacted from every exported artifact.

## Freeze statement

The methodology in this document is frozen. No methodology change is permitted
without issuing a new protocol version. This freeze is a record of approved
methodology only; it is not a live-run authorization.

**Live study status: NOT ADMITTED FOR LIVE STUDY.**
**External human approval verified: `false`.**
