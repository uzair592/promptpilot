# Human decision sheet — production_pipeline_paired_v1

**Date drafted:** 2026-10-02
**Repository revision at draft:** `19843870e48c45a4bdff55a9c84553f4eecadb74`
**Status:** APPROVED METHODOLOGY / PENDING LIVE AUTHORIZATION
**External human approval verified:** `false`
**Live study status:** NOT ADMITTED FOR LIVE STUDY

This sheet records the approved methodological decisions. It does **not** record
identity-verified human approval of fixtures or authorization to spend credits.
No reviewer identity, signature, consent, or approval timestamp is asserted here.

## Decision record

| # | Decision | Approved value | Status |
|---|----------|-----------------|--------|
| D1 | Dataset | all 8 tasks, unchanged | APPROVED |
| D2 | Repetitions R | 3 | APPROVED |
| D3 | Condition order | alternating, persisted (B→P, P→B, B→P) | APPROVED |
| D4 | Question cap Q | 2 | APPROVED |
| D5 | Unmatched gap | `skip` with explicit unresolved record | APPROVED |
| D6 | Unanswered question | `skip` with explicit unresolved record | APPROVED |
| D7 | Fabrication of missing answers | prohibited | APPROVED |
| D8 | Primary fallback admission | `reject` | APPROVED |
| D9 | Fallback run handling | diagnostic retention only, never relabelled | APPROVED |
| D10 | Primary evaluator | `llm_judge` | APPROVED |
| D11 | Secondary evaluator | none | APPROVED |
| D12 | Rubric | `v1`, weights unchanged | APPROVED |
| D13 | Aggregation | backend-owned weighted sum, unchanged | APPROVED |
| D14 | Judge payload | neutral A/B, no condition identity | APPROVED |
| D15 | A/B-to-condition mapping | stored separately, not shown to judge | APPROVED |
| D16 | Human review sample | 8 pairs, one per task, preselected before results | APPROVED |
| D17 | Human reviewers | 2, blinded to condition | APPROVED |
| D18 | Human rubric | same five `v1` dimensions, neutral A/B | APPROVED |
| D19 | Disagreement threshold | per-dimension difference > 20 points | APPROVED |
| D20 | Adjudication | third human reviewer or predeclared consensus procedure | APPROVED |
| D21 | Primary strata | `overall` and `task category` only | APPROVED |
| D22 | Extra strata | prohibited in primary; exploratory must be labelled | APPROVED |
| D23 | Target temperature | 0 | APPROVED |
| D24 | Target top_p | 1.0 | APPROVED |
| D25 | Target stop | `[]` | APPROVED |
| D26 | Target presence_penalty | 0 | APPROVED |
| D27 | Target frequency_penalty | 0 | APPROVED |
| D28 | Target seed | `null` | APPROVED |
| D29 | Target provider | PENDING — no value invented | PENDING |
| D30 | Target model | PENDING — no value invented | PENDING |
| D31 | Target max_tokens | PENDING — no value invented | PENDING |
| D32 | Target timeout | PENDING — no value invented | PENDING |
| D33 | Call budget | 168 total across fixed roles, no retries | APPROVED |
| D34 | Baseline definition | original task only, same target model | APPROVED |
| D35 | Treatment definition | full production pipeline, same target model | APPROVED |
| D36 | Target identity | same provider/model/params for both conditions | APPROVED |
| D37 | Scope separation | `production_pipeline_paired_v1` distinct from `benchmark_infrastructure_smoke_test` | APPROVED |
| D38 | Human review identities | not fabricated; external verification required | APPROVED |
| D39 | External approval flag | `false` until externally verified | APPROVED |
| D40 | Live execution | not run | APPROVED (as a hold) |

## Human review plan (FROZEN)

* **Sample:** 8 benchmark pairs, one pair from each of the 8 tasks.
* **Selection timing:** the sample is preselected **before** any results are
  seen. Selection is not made after results are observed.
* **Reviewers:** 2, each blinded to condition identity.
* **Presentation:** neutral A/B labels, no condition names.
* **Rubric:** the same five `v1` dimensions as the automatic judge
  (relevance, completeness, instruction_following, contextual_grounding,
  clarity).
* **Procedure:** the two reviewers score independently.
* **Disagreement:** a per-dimension difference greater than 20 points is
  flagged.
* **Retention:** both reviewers' scores are retained, including disagreements.
  Neither score is discarded or averaged away silently.
* **Adjudication:** flagged disagreements are resolved by a third human reviewer,
  or by a consensus procedure declared in advance. The procedure is predeclared
  before adjudication begins.
* **Identities:** no reviewer identity, signature, or consent is fabricated. Any
  real identity must be supplied and externally verified by a human.

## Budget (FROZEN)

| Role | Calls |
|------|-------|
| analysis | 24 |
| question_generation | 48 |
| prompt_generation | 24 |
| target_execution | 48 |
| judge | 24 |
| **Total** | **168** |

No hidden safety budget. No automatic target retry. No silent ceiling increase.

## Explicitly not decided

The following remain open and MUST NOT be filled in by software, inference, or
assumption: target provider, target model, target `max_tokens`, target
`timeout`, fixture reviewer identities, fixture review timestamps, provenance
and consent evidence references, provider authorization, spending authorization,
and external human approval.

## Research status at this draft

* Research decision — COMPLETE
* Methodology freeze — COMPLETE
* Safety and budget ledger — IMPLEMENTED AND OFFLINE-VALIDATED
* Benchmark infrastructure — IMPLEMENTED
* Human-reviewed fixtures — NOT CREATED
* Controlled live pilot — NOT RUN
* Validated benchmark results — NOT ESTABLISHED
* Superiority claim — NOT MADE

**Live study status: NOT ADMITTED FOR LIVE STUDY.**
**External human approval verified: `false`.**
