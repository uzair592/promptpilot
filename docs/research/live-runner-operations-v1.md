# Live runner operations and launch gates — v1

**Status:** IMPLEMENTED AND FAIL-CLOSED
**External human approval verified:** `false`
**Live study status:** NOT ADMITTED FOR LIVE STUDY
**Live experiment run:** NONE — no live provider call has ever been made
**Valid benchmark result:** NONE — no valid benchmark result exists yet

This document describes the guarded live runner that exists in the
`feat/guarded-live-runner` branch. The live **infrastructure** is
implemented in code, but live **execution** remains fail-closed: the
software can never authorize a live run, and no live experiment has
been run.

## The three facts that must stay separate

1. **Live infrastructure exists in code.** `ExecutionMode` has two
   members, `offline_dry_run` and `live`. `LiveExperimentRunner`,
   `ProviderCallExecutor`, `LiveProviderAdapter`, and the
   `ProviderAdapterFactory` live mode are all implemented.
2. **Live execution is still fail-closed.** Every live path requires a
   launch-gate report carrying `ready = true`. The software never
   produces one: `evaluate_launch_gate` always reports
   `ready = false`, because software cannot verify human
   authorization. A `ready = true` report can only be supplied by a
   human-controlled process that has completed the out-of-band
   admission.
3. **Live execution is not authorized merely because the software
   exists.** Passing tests, a staged run, or a technically-ready
   report are not authorization. The real production experiment
   remains unauthorized until the genuine human-controlled
   prerequisites below are completed.

## What the implementation provides

| Component | File | Purpose |
|---|---|---|
| Launch authorization boundary | `benchmark_experiment_authorization.py` | Models an externally issued authorization claim and a fail-closed launch gate. Never manufactures approval. |
| Protocol/fixture binding | `benchmark_experiment_binding.py` | Pins a run to the exact protocol, dataset, fixture hashes, and target parameters it was admitted against. |
| Provider-call execution gate | `benchmark_experiment_execution.py` | Forces every provider-backed stage through `reserve_call -> mark_started -> provider invocation -> mark_succeeded/mark_failed`. |
| Stop-rule evaluator | `benchmark_stop_rules.py` | Fail-closed stop rules wired into the live runner at every decision point. |
| Guarded live runner | `benchmark_live_runner.py` | Per-unit production treatment pipeline; every provider call is ledger-gated. |
| Provider adapter boundary | `benchmark_provider_adapter.py` | Separates offline fixture adapters from the live `OpenAICompatibleProvider` adapter. |
| Results and export contract | `benchmark_experiment_results.py` | Immutable per-unit provenance, four explicit dispositions, score-free blinded review samples separated from human review records, export plus `ExportLock`. |
| Analysis and dry-run planning | `benchmark_experiment_analysis.py` | Deterministic aggregation over frozen strata and the offline workload plan. |
| Study preparation and readiness | `benchmark_study_preparation.py` | The deterministic human-input checklist, the canonical content-addressed study configuration, and the offline preparation/staging rehearsal. Never manufactures a human decision. |
| Operational CLI | `benchmark_live_runner_cli.py` | `validate`, `dry-run`, `stage`, `inspect`, `launch-gate`, `validate-study`, `inspect-study`, `validate-fixtures`, `validate-pricing`, and `stage-study`. No `run` command. |

## Execution modes

### `offline_dry_run`

Admits only providers explicitly marked `offline_fixture = True`.
The engine rejects anything without `offline_fixture = True` and
rejects `OpenAICompatibleProvider` by type. No network call, no
credential read, no cost. This is the only mode the offline engine
and the dry run use.

### `live`

Requires **all** launch-gate conditions to pass and a launch-gate
report with `ready = true`. The `ProviderCallExecutor` refuses live
execution unless the report is present, is ready, and is internally
consistent (every frozen condition flag it records is itself
satisfied). Offline fixture providers are rejected in live mode, so
a synthetic fixture can never reach a live provider.

## Frozen research configuration

| Setting | Value |
|---|---|
| Tasks | the 8 existing benchmark tasks, unchanged |
| Repetitions R | 3 |
| Question cap Q | 2 |
| Unmatched gap | `skip` |
| Unanswered question | `skip` |
| Fallback admission | `reject` |
| Primary evaluator | `llm_judge` |
| Secondary evaluator | none |
| Rubric | `v1` (25/20/20/20/15) |
| Condition order | rep 1 `baseline -> PromptPilot`, rep 2 reverse, rep 3 `baseline -> PromptPilot` |
| Analysis strata | `overall`, `task_category` |
| Human review | 8 pairs, one per task, 2 blinded reviewers, >20-point disagreement threshold |
| Call ceiling | 168 (analysis 24, questions 48, prompt 24, target 48, judge 24) |

Target generation parameters are frozen: `temperature = 0`, `top_p = 1.0`,
`stop = []`, `presence_penalty = 0`, `frequency_penalty = 0`, `seed = null`.
Both conditions resolve to one identical parameter set, or
`assert_target_parameters_identical` fails.

## Still human decisions

Target provider, target model, `max_tokens`, `timeout`, provider
authorization, spending authorization, genuine fixture review and
admission, and external human approval. Software supplies none of
these and must not guess any of them. The readiness checklist
reports each as a machine-readable blocker when it is absent; it
never fills in a value.

## Launch sequence

1. **Human research decisions complete.** R, Q, skip policies, fallback
   admission, evaluator, rubric, strata, and budget are fixed and recorded.
2. **Human-reviewed fixtures complete.** Each of the 8 tasks receives a real
   `experimental_candidate` fixture with genuine reviewer identity, review
   timestamp, and provenance/consent evidence. Synthetic fixtures are never
   promoted and are permanently not live-eligible.
3. **Target provider and model selected.** A single provider/model binding, used
   identically by both conditions.
4. **Target parameters frozen.** `max_tokens` and `timeout` are chosen and
   recorded. Both conditions must resolve to one identical parameter set.
5. **Provider access authorized.** Confirmed with the provider owner.
6. **Spending authorized.** A budget and currency are confirmed.
7. **Protocol locked.** The protocol document is frozen; its hash is the study
   identity.
8. **Admission validates.** `admit_protocol` returns `ready = true` with
   `human_approval.externally_verified = false`. Technical readiness is not
   authorization.
9. **Launch authorization supplied.** An external authorization artifact is
   issued out of band and presented to `evaluate_launch_gate`. It must bind to
   the frozen protocol hash, grant provider and spending access, cover the
   exact provider/model pair, and point at externally held evidence.
10. **Launch gate evaluated.** `evaluate_launch_gate` reports technical
    readiness but always `ready = false`. A human-controlled process completes
    the admission and supplies a `ready = true` launch-gate report.
11. **Ledger-bound experiment staged.** `BenchmarkCallLedger.stage_run` freezes
    role bindings, per-role ceilings, and the total ceiling of 168.
12. **Controlled benchmark run.** `LiveExperimentRunner` executes each unit.
    Every provider call is reserved before it is invoked. No reservation, no
    call. The stop-rule evaluator halts on any frozen-protocol violation.
13. **Immutable export.** Results are exported with every unit's disposition and
    reason code. Unsuccessful units are retained, never deleted. `write_export`
    refuses to overwrite an existing export, writes a companion `ExportLock`
    record beside it, and returns that lock.
14. **Results locked.** The companion `ExportLock` records the SHA-256 of the
    exact UTF-8 bytes written to the export file, plus the export schema
    version, protocol SHA-256, dataset SHA-256, unit count, disposition counts,
    and a lock timestamp. The lock is derived from the serialized export bytes
    and is stored *outside* the export, so the hash cannot be perturbed by the
    lock's own fields. Verification re-hashes the file as stored rather than
    re-serializing a parsed model, so any change to the bytes is caught even
    when the document still parses to an equivalent export.
15. **Analysis without methodology change.** Aggregation runs over the frozen
    strata. Additional breakdowns are labelled exploratory.

### Human-review sample and review results are separate types

The pre-review artifact is structurally score-free:

| Type | Responsibility | May carry scores? |
|---|---|---|
| `HumanReviewSampleSlot` | blinded pair awaiting review: pair id, task id, repetition, response A, response B, neutral-label reference, rubric version, review/adjudication status | **No** — has no reviewer field and no score field at all |
| `HumanReviewRecord` | actual reviewer + dimension + score + notes + disagreement flag | Yes, and only here |

`HumanReviewPlan.slots` holds the score-free samples; `HumanReviewPlan.records`
holds real review data and is empty until a human actually reviews a pair. The
application never populates it. The blinded sample exposes no condition or
model identity, so a reviewer cannot infer which response is the baseline.

## Launch gate

`evaluate_launch_gate` reports `ready = true` only when every condition holds.
The software never sets `ready = true`; that field is reserved for external
human admission.

| Condition | Blocker code when it fails |
|---|---|
| Protocol locked | `protocol_not_locked` |
| Technical admission ready | `protocol_admission_failed` |
| Fixture set non-empty | `fixture_set_empty` |
| Every selected fixture live-eligible | `fixtures_not_live_eligible` |
| Authorization supplied | `launch_authorization_absent` |
| Authorization bound to this protocol | `authorization_protocol_mismatch` |
| Provider access granted | `provider_not_authorized` |
| Spending granted | `spending_not_authorized` |
| Authorized provider/model matches target | `authorized_provider_mismatch` |
| Authorized budget matches protocol budget | `authorized_budget_mismatch` |
| Fresh hash-pinned pricing snapshot | `pricing_snapshot_unverified` |
| Runtime HTTPS provider identity matches every frozen role | `provider_configuration_unavailable` |
| Human admission verified out of band | `human_admission_unverified` (always present for software) |

If any single condition fails, no provider may be called. The
`ProviderCallExecutor` re-verifies that a `ready = true` report is
internally consistent, so no single condition can be unsatisfied while
the report still claims readiness.

## Why software cannot fabricate approval

`LiveLaunchAuthorization` is a **claim document**, not a verification verdict.

* It has **no `verified` field**. Adding a boolean the application could set
  would be exactly the failure mode this boundary exists to prevent.
* Evidence and issuer references must carry an external scheme (`https`, `urn`,
  `mailto`, `did`). A local path or a checked-in JSON file is rejected, so the
  repository cannot authorize itself. Insecure `http` is rejected.
* Placeholder values (`TBD`, `unknown`, `placeholder`, `example.com`, `test`,
  `dummy`, `n/a`) are rejected, so an unfilled draft cannot pass as an
  authorization.
* `provider_authorized` and `spending_authorized` are literal `True`, so a
  withheld grant fails closed at parse time.
* The gate records an explicit `software_verification_limit` stating that
  authenticity of the issuer, any signature, and any consent remain unverified
  claims requiring out-of-band human confirmation.
* `BenchmarkExperimentRun.external_human_approval_verified` remains constrained
  to `false` by a database CHECK constraint, and `HumanApprovalBoundary` still
  refuses `externally_verified = true`. Neither was weakened.

## Offline dry run

`plan_dry_run` computes the exact frozen workload with no execution:

| Quantity | Value |
|---|---|
| Units | 24 (8 tasks x 3 repetitions) |
| Pairs | 24 |
| analysis | 24 |
| question_generation | 48 |
| prompt_generation | 24 |
| target_execution | 48 |
| judge | 24 |
| **Total** | **168** |
| Network calls | 0 |
| Cost estimate | 0 |

The dry run cannot accept a real provider instance: the engine rejects anything
without `offline_fixture = True` and rejects `OpenAICompatibleProvider` by type.

## Study preparation and admission readiness

`benchmark_study_preparation.py` implements the preparation milestone. It
never executes the study, never contacts a provider, never spends credits,
and never manufactures a human decision. It validates human-supplied
declarations and reports exactly what is still missing.

### Readiness checklist

`evaluate_study_readiness` returns a `StudyReadinessReport` that separates
what software can verify from what only a human can decide:

| Field | Meaning |
|---|---|
| `technical_ready` | Every software-verifiable check passed. |
| `human_approval` | Always `false` here; software cannot verify human approval. |
| `authorized` | Always `false` here; software cannot verify authorization. |
| `live_execution_ready` | Always `false`; software can never authorize a live run. |

The report carries a machine-readable `checks` list (one named question
with a ready/not-ready answer) and a `blockers` list (one machine-readable
reason per failure). The `software_verification_limit` field states that the
authenticity of any reviewer, issuer, signature, consent, or authorization
remains an unverified claim requiring out-of-band human confirmation.

The checklist verifies, in order: protocol locked, dataset identity, the
frozen 8-fixture / R=3 / Q=2 shape, every fixture hash current and
live-eligible, every fixture carries human review evidence, both conditions
resolve to one identical frozen parameter set, `max_tokens` chosen,
`timeout` chosen, every frozen provider role assigned, a fresh hash-pinned
pricing snapshot covers every role, a monetary budget with a maximum spend
and currency is configured, provider/spending/external-human authorization
supplied, technical admission ready, and the launch gate technically
capable of passing.

### Canonical study configuration

`build_study_configuration` produces a `StudyConfiguration`: a single
content-addressed artifact that binds the protocol SHA-256, dataset
SHA-256, all 8 fixture SHA-256s, the provider/model/judge assignments,
the frozen target parameters, the chosen `timeout`, the question cap, the
skip and fallback policies, the evaluator, the rubric version, the
condition order, the repetitions, the monetary budget, the pricing
snapshot reference, and the 168-call ceiling. The configuration is
content-addressed by its own canonical SHA-256, so the study cannot be
silently re-interpreted under a different configuration.

### Offline rehearsal

`rehearse_study_preparation` (CLI: `stage-study`) rehearses the complete
preparation/staging workflow offline. It uses only the supplied
declarations and the offline dry-run planner. It makes zero network
calls, zero real provider calls, spends zero money, and never produces a
live-eligible fixture or a human approval. It proves the staging machinery
works without involving real infrastructure.

### Study-preparation CLI

| Command | Purpose |
|---|---|
| `validate-study` | Evaluate the readiness checklist; exit non-zero when blocked. |
| `inspect-study` | Print (and optionally write) the canonical study configuration and its SHA-256. |
| `validate-fixtures` | Validate every selected fixture manifest offline; report live-eligibility and hash match. |
| `validate-pricing` | Validate the offline, hash-pinned provider pricing snapshot. |
| `stage-study` | Rehearse the complete preparation/staging workflow offline (zero network, zero cost). |

`max_tokens` and `timeout` are required human decisions with no default.
`validate-study`, `inspect-study`, and `stage-study` fail closed when
either is absent; the software never guesses a value.

## Budget enforcement

The authoritative order is:

```
reserve_call
    -> mark_started
    -> provider invocation
    -> mark_succeeded OR mark_failed
```

A provider is never invoked before **both** a successful reservation and the
transition to `started`. The role counter is consumed at reservation time, so a
call can neither exceed the ceiling nor vanish from the ledger. The monetary
reservation is applied atomically against the authoritative database state
(`spent_amount + reserved_spend + estimated_cost <= max_spend`), so concurrent
reservations cannot oversubscribe the budget. There is no hidden safety budget
and no silent ceiling increase. Replaying an identical idempotency key returns
the recorded outcome without invoking the provider again. A settled cost cannot
exceed its reservation.

## Stop rules

The `StopRuleEvaluator` is wired into the live runner at every decision point:

| Rule | Enforced by | Stop reason code |
|---|---|---|
| Launch gate | `ProviderCallExecutor` (authoritative); `evaluate_launch_gate` (redundant preflight) | `launch_gate_not_passed` |
| Protocol drift | `evaluate_before_target_execution` before every target call | `protocol_drift` |
| Fixture drift / re-verification | `verify_fixture_before_target_execution` and `evaluate_before_target_execution` before every target call | `fixture_drift` |
| Fixture live-eligibility | `verify_fixture_before_target_execution` and `evaluate_before_target_execution` (live mode) | `fixture_not_live_eligible` |
| Target-parameter identity | `evaluate_before_target_execution` and `assert_target_parameters_identical` | `invalid_target_parameters` |
| Condition order | `evaluate_before_target_execution` and `approved_condition_order` | `invalid_condition_order` |
| Target provider/model identity | `evaluate_before_target_execution` and the ledger reservation | `provider_authorization_mismatch` |
| Call ceiling | `reserve_call` (atomic) | `budget_exhausted` |
| Monetary budget | `reserve_call` (atomic) and `evaluate_before_target_execution` | `monetary_budget_exhausted` |
| Provider-call outcome | `evaluate_after_provider_call` after every settled call | `provider_failure` |
| Fallback admission | `evaluate_fallback` whenever a fallback is observed | `fallback_rejected` |
| Pair completeness | `evaluate_pair_completeness` after every unit | `incomplete_required_pair` |
| Judge requirement and failure | `evaluate_judge_result` after every paired evaluation | `judge_failure` |
| Idempotency | `reserve_call` (authoritative); `evaluate_idempotency` (redundant preflight) | `idempotency_violation` |

A failing stop decision halts the unit and records the disposition and reason
code; it is never silently converted into a successful outcome.

## Provider failure handling

Lifecycle: `reserved -> started -> succeeded | failed`, plus `reserved ->
cancelled`.

* A failed call stays visible as `failed` with a safe error type and code; raw
  exception text is never persisted.
* A failure is never recorded as success.
* Failures are not retried silently.
* Failures do not exceed budget: the role counter was already consumed at
  reservation.
* Under `fallback_admission = reject`, a fallback-containing run is never
  admitted as ordinary primary evidence. Diagnostic artifacts are retained, but
  the run is never relabelled and never silently excluded without a reason code.

## Baseline isolation

The baseline condition executes the exact original task and nothing else. The
request passed to the target provider for baseline is
`{"prompt": original_task, "parameters": frozen_parameters}`. The baseline
receives no PromptPilot analysis, questions, answers, project memory, documents,
retrieved context, assembled context, optimized prompt, `PromptVersion`, or
treatment metadata. Both conditions use the same target provider, model,
parameters, output limits, timeout policy, and stop configuration; only the
experimental prompt differs.

## Judge blinding

Baseline and PromptPilot responses are randomly mapped to neutral `Response A` /
`Response B` labels. The judge receives only the neutral labels and never the
condition identity. The condition mapping is retained outside the judge prompt in
the evaluation metadata. Scores are mapped back to baseline vs PromptPilot, and
`overall_delta = PromptPilot - baseline`. The primary evaluator is always
`llm_judge`; no heuristic fallback may silently replace it. Any judge failure is a
failure/invalid disposition, not a successful evaluation.

## Remaining prerequisites before the first real provider call

These are genuine human-controlled prerequisites, not engineering tasks:

1. Complete the human research decisions listed above.
2. Obtain genuine human-reviewed `experimental_candidate` fixtures for all 8 tasks.
3. Select and confirm the target provider, model, `max_tokens`, and `timeout`.
4. Obtain provider access authorization and spending authorization out of band.
5. Lock the protocol and record its hash.
6. Use `validate-study` to confirm the readiness checklist has no
   software-verifiable blockers, and `stage-study` to rehearse the
   offline preparation/staging workflow. A clean rehearsal is not
   authorization; it only proves the staging machinery works.
7. Complete the human-controlled admission and supply a `ready = true`
   launch-gate report bound to the frozen protocol.
8. Only then may a human-controlled process start `LiveExperimentRunner` in
   `live` mode.

## Research status at this milestone

```
Benchmark infrastructure: IMPLEMENTED
Benchmark safety/budget ledger: IMPLEMENTED AND OFFLINE-VALIDATED
Study preparation and readiness checklist: IMPLEMENTED AND OFFLINE-VALIDATED
Canonical study configuration artifact: IMPLEMENTED
Offline preparation/staging rehearsal: IMPLEMENTED (zero network, zero cost)
Controlled live pilot: NOT RUN
Validated benchmark results: NOT ESTABLISHED
General PromptPilot superiority claim: NOT MADE
```

The project goal is not for PromptPilot to win. It is to measure honestly.
