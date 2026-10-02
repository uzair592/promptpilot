# Live-study admission report

Generated from an offline audit of the repository as of `0b1dd0d` on branch
`feat/benchmark-provider-call-ledger` against `origin/main` at `83a8e01`.

This report makes no provider calls, consumes no API credits, and introduces no live
data. It records the current state of each live-study prerequisite.

## Software readiness

The implementation is technically capable of enforcing the study protocol.

- **Ledger:** `BenchmarkCallLedger` stages a run only against a technically ready
  admission report whose protocol hash, dataset hash, admitted fixture set, and call
  ceiling all match the frozen protocol. Reservation is a single conditional database
  update that checks run state plus per-role and total ceilings, and the attempt insert
  is committed in the same transaction. Idempotency is enforced by a
  `(run_id, idempotency_key)` unique constraint. Attempt identity is immutable after
  insertion. Termination claims the run state with a conditional update and checks the
  affected-row count.
- **Benchmark:** `production_benchmark_offline.OfflinePipelineBenchmark` orchestrates
  the existing production services behind an offline-only boundary that requires
  explicitly injected offline providers.
- **Evaluation:** the unchanged `v1` rubric and backend-owned weighted aggregate are
  used; evaluation-only criteria enter evaluation only after both target runs.
- **Offline validation:** 242 backend tests pass; 39 ledger tests pass including the
  final-slot race, idempotency, immutable identity, terminal-state protection, exact
  budget, and provider-call ordering.

## Protocol readiness

The protocol contract is frozen and machine-checkable. The `v1` schema forbids extra
fields, rejects unresolved placeholders and credential-like values, and fixes:

- dataset name and canonical hash;
- selected fixtures, manifest paths, manifest hashes, and review attestations;
- repetitions, question cap, unmatched-gap handling, fallback admission, and analysis
  stratum;
- generation mode and primary/secondary evaluation methods;
- provider/model assignments for every role, identical target assignment, and exact
  target parameters;
- alternating paired order, exact-original-task baseline, task/repetition isolation,
  and prohibition on evaluating incomplete pairs;
- per-role and total call budgets, stop rules, and locked protocol review metadata.

**Incomplete items requiring a human decision:**

- which exact tasks/fixtures are selected for the live study;
- the repetition count;
- the question cap and unmatched-gap behavior;
- whether fallbacks are rejected or admitted only in a separate hybrid stratum;
- the primary and optional secondary evaluation methods;
- the role-specific providers/models and exact target parameters;
- the per-role, total, and optional monetary budgets;
- the analysis stratum name.

These are research-policy choices. The software enforces them once frozen; it does not
choose them. They are recorded here as **Human decision required**.

## Human approval

**NOT VERIFIED.**

`external_human_approval_verified` is locked to `false` at three independent
boundaries:

1. the ledger service hardcodes it on every staged run;
2. the database CHECK constraint `external_human_approval_verified = false` rejects any
   row that attempts to set it true;
3. `HumanApprovalBoundary` raises if `externally_verified=True` is submitted to the
   validator.

The software can verify that an approval claim exists and is internally consistent. It
cannot manufacture the approval. Tests passing, an AI agent declaring readiness, a
fixture existing, or the protocol being syntactically valid never set this field.

No checked-in fixture supplies authentic live-study evidence. Reviewer identities,
consent/provenance evidence, and human-approved manifests must be provided and
externally verified by the study owner before a live run.

## Provider readiness

**NOT CONFIGURED.**

No live provider is configured for this milestone. The ledger rejects the live
`OpenAICompatibleProvider` and requires every injected provider to be marked
`offline_fixture=True`. Provider access, model assignments, and spending authorization
must be explicitly granted by the study owner before a live run.

## Budget readiness

The ledger and the declared budget agree by construction. Staging requires
`declared budget == calculated ceiling` exactly; both too-low and too-high totals are
rejected with `protocol_budget_mismatch`. The database enforces the same invariant with
a `total_call_ceiling = sum(role ceilings)` CHECK constraint.

For the checked-in synthetic protocol (1 fixture, 2 repetitions, question cap 2,
heuristic-only evaluation) the calculated ceiling is analysis 2, question generation 4,
prompt generation 2, target execution 4, judge 0, total 12.

## Dataset readiness

**NOT HUMAN-REVIEWED.**

The checked-in dataset is `promptpilot-experimental-v1`, SHA-256
`8b7aca964ffae59151a3c8c24a3412823b7d96ff7739d66e9b79ab71648cc53d`, with 8 tasks
across 7 categories. It is an experimental template, not a human-reviewed live-study
dataset. Inclusion/exclusion rules, category definitions, and fixture/ground-truth
policy are not yet frozen by a human reviewer.

The checked-in synthetic fixture is test-only and is not live-eligible. The offline
admission validator reports `NOT READY` with the deterministic reason
`fixture_not_live_eligible` plus `fixture_set_not_fully_admitted`.

## Final gate

**NOT ADMITTED FOR LIVE STUDY**

Software readiness and protocol structure are in place, but human review, provider
configuration, and a frozen dataset have not occurred. No live provider call has been
made and no API credits have been consumed.

## Remaining decisions requiring human input

- select the exact tasks/fixtures and repetition count;
- freeze the question cap, unmatched-gap behavior, fallback admission, and analysis
  stratum;
- freeze the evaluation methods and the target provider/model and exact generation
  parameters;
- freeze the per-role, total, and optional monetary budgets;
- review and freeze the dataset, including inclusion/exclusion rules and ground-truth
  policy;
- provide externally verified reviewer identities, consent/provenance evidence, and
  human-approved manifests;
- explicitly authorize provider access and spending.

These decisions cannot be made by the software or by an automated agent.