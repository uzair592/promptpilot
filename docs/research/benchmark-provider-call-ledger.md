# Benchmark provider-call ledger

Status: durable accounting and technical admission binding implemented and offline-hardened;
no live runner, provider construction, external approval, or execution authorization is included.

## Schema

`benchmark_experiment_runs` stores the owner, scope, execution mode, admitted protocol
and dataset hashes, frozen provider-role bindings, declared per-role and total call
ceilings, accounting counters, lifecycle timestamps, safe terminal reason codes, and an
optional repository commit SHA. `external_approval_verified` is deliberately fixed to
false because this technical component cannot verify human approval.

`benchmark_provider_call_attempts` stores a stable unit identity, fixture/task and
repetition, role and condition, sequence and idempotency keys, frozen provider/model and
generation-parameter hashes, safe input and response artifact hashes, lifecycle state,
reported token usage, optional finite cost and currency, and safe failure/fallback/
observation classifications. It does not store prompts, responses, credentials,
authorization headers, cookies, or credential-bearing URLs.

Database checks constrain states, roles, counts, usage, and costs. Uniqueness constraints
cover `(run_id, idempotency_key)` and `(run_id, sequence_number)`. ORM update protection
rejects mutation of an attempt's immutable identity after insertion.

## Exact budgets

A frozen protocol must declare `total == sum(role ceilings)`. Declaring more is not a
budget: an over-declared ceiling would decouple the protocol from its calculated worst-case
cost, so staging rejects both too-low and too-high totals with `protocol_budget_mismatch`.
The database enforces the same invariant with a `total_call_ceiling = sum(role ceilings)`
CHECK constraint, so an inconsistent row cannot be persisted even outside the service.

## SQLite vs PostgreSQL

The reservation gate is a single conditional `UPDATE ... RETURNING` that checks run state
plus role and total ceilings in one statement, and the attempt insert is committed in the
same transaction. SQLite serializes writers per database file, so the conditional update
plus the uniqueness constraint are sufficient there. PostgreSQL enforces the same
invariants with row-level locking and the same constraint set. The invariant is
database-enforced in both dialects; this milestone has been validated on SQLite only and
has not been production-validated on PostgreSQL.

## State machines

A run moves from `staged` to `running`, then to `completed`, `failed`, or `aborted`.
Terminal runs cannot accept reservations. Completion requires no reserved or started
attempts and internally consistent counters. Failure and abort settle outstanding
attempts without losing their durable audit rows.

An attempt moves from `reserved` to `started`, then to `succeeded` or `failed`. A
reservation may instead move directly to `cancelled` before execution. Duplicate or
out-of-order transitions fail closed.

## Atomic reservation and idempotency

Reservation first verifies the run and immutable declaration: role, protocol and dataset
hashes, provider/model binding, target-condition equivalence, and generation-parameter
hash. One conditional SQL `UPDATE ... RETURNING` then checks the run state plus the
role and total ceilings while incrementing the role-consumption count, reserved count,
and next sequence number. The attempt insert is committed in the same transaction.
Consequently, competing transactions cannot both consume the final slot on supported
databases, including the SQLite test configuration and PostgreSQL deployment schema.

Reusing an idempotency key with an identical immutable declaration returns the existing
attempt without consuming another slot. Reusing it for a different declaration is an
error. The database uniqueness constraint is the final race-safe guard.

## Budget accounting

Reserved and started attempts count as reserved. Success or failure releases the
reservation counter and increments its terminal counter, while retaining role and total
consumption. Cancelling before execution releases both the reservation and the consumed
role slot. A snapshot reports ceilings, role consumption, and reserved/succeeded/failed/
cancelled totals without consulting a provider.

## Protocol and artifact binding

Staging independently revalidates an already parsed `LiveStudyProtocol` and
`AdmissionReport`. It requires technical readiness, the existing report's `ready=true`
semantics, no blockers, matching canonical protocol and dataset hashes, the exact
admitted fixture set, and calculated call ceilings consistent with the frozen budgets.
The target baseline and PromptPilot conditions share one frozen target provider/model.

Canonical JSON hashing sorts keys, uses compact UTF-8 serialization, and rejects NaN or
infinity. The ledger stores hashes or safe references rather than raw model inputs and
outputs. Credential-like fields and values are rejected, and provider exceptions are
reduced to a safe exception type plus controlled error code; raw exception text is never
persisted.

## Authorization boundary

This milestone provides durable technical accounting only. It does not read environment
credentials, instantiate providers, send network requests, verify reviewer identity or
consent, create approved fixtures, or authorize a study. Before a live runner exists,
external human approval and provenance must be verified, provider access and spending
must be explicitly authorized, operational recovery and monitoring must be reviewed, and
the runner itself must preserve the admitted protocol, ledger, and evidence boundaries.
