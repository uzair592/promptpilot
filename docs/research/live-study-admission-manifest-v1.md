# Live-study admission manifest v1

Checklist for converting the frozen protocol into an authorized live study.

Every item is recorded as **APPROVED** (methodology frozen by a human research
decision) or **PENDING** (an input that only a human can supply).

The system MUST NOT mark human approval as approved automatically. Passing tests,
a valid protocol document, or any machine declaration never sets an approval
item.

---

## Identity

* **Protocol ID:** `production_pipeline_paired_v1`
* **Protocol version:** `v1`
* **Date drafted:** 2026-10-02
* **Repository revision at draft:** `19843870e48c45a4bdff55a9c84553f4eecadb74`
* **Execution mode implemented:** `offline_fixture`
* **external_human_approval_verified:** `false`

---

## Dataset

* [x] **FROZEN** — exact task IDs, categories, dataset version, dataset SHA-256
* [x] **REVIEWED** — inclusion/exclusion rules, category definitions, fixture/ground-truth policy
* [ ] **FIXTURES ADMITTED** — each of the 8 tasks needs a live-eligible, human-reviewed, externally verified fixture
* [x] **DATASET VERSION:** `promptpilot-experimental-v1` (SHA-256: `8b7aca964ffae59151a3c8c24a3412823b7d96ff7739d66e9b79ab71648cc53d`)
* [x] **TASK SET UNCHANGED** — all 8 tasks, no additions, removals, or edits

**Status:** methodology APPROVED; fixtures PENDING HUMAN REVIEW

---

## Condition order

* [x] **REPETITIONS:** 3 (frozen)
* [x] **BALANCED ALTERNATING:** frozen — repetition 1 `baseline -> PromptPilot`, repetition 2 `PromptPilot -> baseline`, repetition 3 `baseline -> PromptPilot`
* [x] **ORDER PERSISTED** — the executed order is stored per pair and auditable

---

## Question policy

* [x] **MAX QUESTIONS PER TASK/REPETITION:** 2 (frozen)
* [x] **NO GENERATION AFTER CAP:** enforced
* [x] **UNMATCHED GAP BEHAVIOR:** `skip` (frozen)
* [x] **UNANSWERED QUESTION BEHAVIOR:** `skip` (frozen)
* [x] **EXPLICIT UNRESOLVED RECORDS:** required for skipped/unanswered questions and for gaps still open at the cap (frozen)
* [x] **NO FABRICATION:** missing answers are never inferred, invented, or recorded as answered (frozen)
* [x] **DUPLICATE QUESTION POLICY:** skip to next gap, logged as `duplicate_question`
* [x] **QUESTION PRIORITIZATION:** dimension weight + gap severity

---

## Fallback policy

* [x] **PRIMARY FALLBACK ADMISSION:** `reject` (frozen)
* [x] **ANALYSIS FALLBACK:** rejected from the primary result set
* [x] **QUESTION FALLBACK:** rejected from the primary result set
* [x] **PROMPT GENERATION FAILURE:** invalid pair (excluded)
* [x] **DOCUMENT INGESTION FAILURE:** invalid pair (excluded)
* [x] **TARGET MODEL FAILURE:** invalid pair (other condition's response retained as evidence)
* [x] **EVALUATION FAILURE:** invalid pair (excluded) — no silent heuristic substitution
* [x] **FALLBACK RUNS:** retained for diagnosis only; never relabelled and never merged into the primary stratum (frozen)

---

## Evaluation method

* [x] **PRIMARY EVALUATOR:** `llm_judge` (frozen)
* [x] **SECONDARY EVALUATOR:** none (frozen)
* [x] **JUDGE PROVIDER/MODEL:** required by the protocol; PENDING selection
* [x] **RUBRIC:** `v1` — relevance 25, completeness 20, instruction_following 20, contextual_grounding 20, clarity 15
* [x] **NEUTRAL A/B PAYLOAD:** original task, shared requirements, shared constraints, per-condition evidence, Response A, Response B (frozen)
* [x] **A/B BLINDING:** the judge prompt and payload must not contain `baseline` or `PromptPilot` (frozen)
* [x] **A/B MAPPING STORED SEPARATELY** from the judge payload, for audit only (frozen)
* [x] **AGGREGATION:** backend-owned weighted sum on a 0–100 scale (frozen, unchanged)
* [x] **EVALUATION FAILURE HANDLING:** `reject` (frozen)

---

## Target model

* [ ] **PROVIDER:** PENDING HUMAN DECISION (must be OpenRouter-compatible)
* [ ] **MODEL:** PENDING HUMAN DECISION
* [x] **TEMPERATURE:** 0 (frozen)
* [x] **TOP_P:** 1.0 (frozen)
* [x] **SEED:** `null` (frozen)
* [x] **STOP:** `[]` (frozen)
* [x] **PRESENCE PENALTY:** 0 (frozen)
* [x] **FREQUENCY PENALTY:** 0 (frozen)
* [ ] **MAX TOKENS:** PENDING HUMAN DECISION
* [ ] **TIMEOUT:** PENDING HUMAN DECISION
* [x] **IDENTICAL FOR BOTH CONDITIONS:** same provider, model, and parameters in both arms (frozen)

---

## Baseline and treatment

* [x] **BASELINE:** exactly `Original Task -> Target Model -> Response`, original task only (frozen)
* [x] **TREATMENT:** full production pipeline ending in the same target model (frozen)
* [x] **ISOLATION:** the baseline receives no analysis, answers, memory, treatment documents, retrieved context, or optimized prompt (frozen)
* [x] **SAME SOURCE TASK AND TASK/REPETITION IDENTITY** across both arms (frozen)
* [x] **SCOPE SEPARATION:** `production_pipeline_paired_v1` is distinct from `benchmark_infrastructure_smoke_test` (frozen)

---

## Budget

* [x] **PER-ROLE CEILINGS:** analysis 24, question_generation 48, prompt_generation 24, target_execution 48, judge 24
* [x] **TOTAL CEILING:** 168 (F=8, R=3, Q=2, J=1, U=24)
* [x] **NO EXTRA SAFETY BUDGET:** enforced by the ledger
* [x] **NO AUTOMATIC TARGET RETRY:** frozen
* [x] **NO SILENT CEILING INCREASE:** frozen

---

## Analysis strata

* [x] **OVERALL:** frozen
* [x] **TASK CATEGORY (8):** frozen
* [x] **ADDITIONAL PRIMARY STRATA:** prohibited; any extra analysis is exploratory and must be labelled as such (frozen)

---

## Human review plan

* [x] **SAMPLE:** 8 benchmark pairs, one pair from each of the 8 tasks (frozen)
* [x] **SELECTION TIMING:** preselected before any results are seen (frozen)
* [x] **NUMBER OF REVIEWERS:** 2 (frozen)
* [x] **BLINDED A/B PRESENTATION:** frozen — no condition names shown
* [x] **EVALUATION DIMENSIONS:** the same five `v1` dimensions as the automatic judge (frozen)
* [x] **INDEPENDENT SCORING:** each reviewer scores independently (frozen)
* [x] **DISAGREEMENT HANDLING:** a per-dimension difference greater than 20 points is flagged (frozen)
* [x] **SCORE RETENTION:** both reviewers' scores are retained, including disagreements (frozen)
* [x] **ADJUDICATION:** a third human reviewer, or a predeclared consensus procedure (frozen)
* [x] **REVIEWER IDENTITIES:** must be supplied and externally verified; never fabricated
* [ ] **CONCRETE SAMPLE PAIR IDS:** PENDING — the preselected pair ids must be recorded before results are seen
* [ ] **REVIEW INSTRUCTIONS DELIVERED TO REVIEWERS:** PENDING

---

## Failure policy

* [x] **PROVIDER TIMEOUT:** invalid pair
* [x] **RATE LIMIT:** invalid pair
* [x] **INVALID PROVIDER RESPONSE:** invalid pair
* [x] **MISSING FIXTURE:** invalid pair
* [x] **UNMATCHED GAP:** `skip` with an explicit unresolved record
* [x] **UNANSWERED QUESTION:** `skip` with an explicit unresolved record
* [x] **QUESTION CAP REACHED:** partial unit, unresolved gaps recorded
* [x] **PROMPT GENERATION FAILURE:** invalid pair
* [x] **EVALUATION FAILURE:** invalid pair
* [x] **BUDGET EXHAUSTED:** failed experiment
* [x] **NO SILENT DELETION:** every exclusion carries a predefined reason code

---

## Data retention

* [x] **ARTIFACTS TO RETAIN:** frozen — task, context, prompts, responses, parameters sent, ids, hashes, timestamps, failures, explicit unresolved records
* [x] **NO CREDENTIALS STORED:** enforced; known secrets and authorization headers are redacted on export

---

## Provider authorization

* [ ] **PROVIDER ACCESS EXPLICITLY GRANTED:** PENDING HUMAN DECISION
* [ ] **SPENDING AUTHORIZATION:** PENDING HUMAN DECISION

---

## Human approval

* [ ] **EXTERNAL_HUMAN_APPROVAL_VERIFIED = TRUE:** only set by genuine out-of-band human review
* [ ] **REVIEWER IDENTITY VERIFIED:** PENDING HUMAN DECISION
* [ ] **CONSENT/PROVENANCE EVIDENCE VERIFIED:** PENDING HUMAN DECISION
* [ ] **APPROVAL TIMESTAMP RECORDED:** PENDING HUMAN DECISION
* [x] **EXTERNAL_HUMAN_APPROVAL_VERIFIED = FALSE** at this draft

**The software cannot self-approve. Passing tests, AI declarations, or protocol
validity never set this.**

---

## Final admission gate

**ALL PENDING ITEMS ABOVE MUST BE APPROVED BEFORE THE FIRST REAL PROVIDER CALL.**

**Current status: NOT ADMITTED FOR LIVE STUDY**
**External human approval verified: `false`**
