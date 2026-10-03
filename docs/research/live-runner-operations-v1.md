# Live runner operations and launch gates — v1

**Status:** DESIGN AND OPERATIONS PROCEDURE ONLY
**This milestone does NOT enable live execution.**
**External human approval verified:** `false`
**Live study status:** NOT ADMITTED FOR LIVE STUDY

This document describes the future procedure for running the controlled
`production_pipeline_paired_v1` experiment. Nothing described here is
implemented as an executable live path in this milestone.

## What this milestone adds

| Component | File | Purpose |
|---|---|---|
| Launch authorization boundary | `benchmark_experiment_authorization.py` | Models an externally issued authorization claim and a fail-closed launch gate. Never manufactures approval. |
| Protocol/fixture binding | `benchmark_experiment_binding.py` | Pins a run to the exact protocol, dataset, fixture hashes, and target parameters it was admitted against. |
| Provider-call execution gate | `benchmark_experiment_execution.py` | Forces every provider-backed stage through `reserve_call -> mark_started -> provider invocation -> mark_succeeded/mark_failed`. Offline dry-run mode only. |
| Results and export contract | `benchmark_experiment_results.py` | Immutable per-unit provenance, four explicit dispositions, score-free blinded review samples separated from human review records, export plus `ExportLock`. |
| Analysis and dry-run planning | `benchmark_experiment_analysis.py` | Deterministic aggregation over frozen strata and the offline workload plan. |

## What this milestone deliberately does not add

* No live runner, no CLI entrypoint, no API route.
* No real provider adapter. `OpenAICompatibleProvider` is never constructed.
* No authorization factory. Nothing in the codebase can mint a
  `LiveLaunchAuthorization`.
* No environment variable or flag that enables live execution.

`ExecutionMode` is a `Literal` with exactly one member, `offline_dry_run`.
There is no `live` member, so requesting live execution is unrepresentable
rather than merely rejected at runtime.

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

## Still human decisions

Target provider, target model, `max_tokens`, `timeout`, provider authorization,
spending authorization, genuine fixture review and admission, and external human
approval. Software supplies none of these and must not guess any of them.

## Future launch sequence

1. **Human research decisions complete.** R, Q, skip policies, fallback
   admission, evaluator, rubric, strata, and budget are fixed and recorded.
2. **Human-reviewed fixtures complete.** Each of the 8 tasks receives a real
   `experimental_candidate` fixture with genuine reviewer identity, review
   timestamp, and provenance/consent evidence. Synthetic fixtures are never
   promoted.
3. **Target provider and model selected.** A single provider/model binding, used
   identically by both conditions.
4. **Target parameters frozen.** `max_tokens` and `timeout` are chosen and
   recorded. Both conditions must resolve to one identical parameter set, or
   `assert_target_parameters_identical` fails.
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
10. **Ledger-bound experiment staged.** `BenchmarkCallLedger.stage_run` freezes
    role bindings, per-role ceilings, and the total ceiling of 168.
11. **Controlled benchmark run.** Every provider call is reserved before it is
    invoked. No reservation, no call.
12. **Immutable export.** Results are exported with every unit's disposition and
    reason code. Unsuccessful units are retained, never deleted. `write_export`
    refuses to overwrite an existing export, writes a companion
    `ExportLock` record beside it, and returns that lock.
13. **Results locked.** The companion `ExportLock` records the export content
    SHA-256, export schema version, protocol SHA-256, dataset SHA-256, unit
    count, disposition counts, and a lock timestamp. The lock is derived from
    the exact serialized export bytes and is stored *outside* the export, so the
    hash cannot be perturbed by the lock's own fields. `ExportLock.verify`
    re-checks the export against the lock and fails on any mismatch.
14. **Analysis without methodology change.** Aggregation runs over the frozen
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

`evaluate_launch_gate` reports `ready = true` only when every condition holds:

| Condition | Blocker code when it fails |
|---|---|
| Protocol locked | `protocol_not_locked` |
| Fixture set non-empty | `fixture_set_empty` |
| Every selected fixture live-eligible | `fixtures_not_live_eligible` |
| Authorization supplied | `launch_authorization_absent` |
| Authorization bound to this protocol | `authorization_protocol_mismatch` |
| Provider access granted | `provider_not_authorized` |
| Spending granted | `spending_not_authorized` |
| Authorized provider/model matches target | `authorized_provider_mismatch` |

If any single condition fails, no provider may be called.

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
call can neither exceed the ceiling nor vanish from the ledger. There is no
hidden safety budget and no silent ceiling increase. Replaying an identical
idempotency key returns the recorded outcome without invoking the provider again.

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

## Next engineering milestone

Before the first real provider call, a live-adapter milestone must still:

1. implement the real provider adapter behind an explicit live mode;
2. implement the per-unit treatment pipeline against the frozen protocol;
3. enforce monetary budget at runtime (validated but not yet enforced in the ledger);
4. enforce `StopRules` at runtime (validated but not yet enforced);
5. add per-unit fixture re-verification immediately before each target call;
6. add CLI/API entrypoints for staging and running a live experiment;
7. obtain the human decisions listed above.

## Research status at this milestone

```
Benchmark infrastructure: IMPLEMENTED
Benchmark safety/budget ledger: IMPLEMENTED AND OFFLINE-VALIDATED
Controlled live pilot: NOT RUN
Validated benchmark results: NOT ESTABLISHED
General PromptPilot superiority claim: NOT MADE
```

The project goal is not for PromptPilot to win. It is to measure honestly.