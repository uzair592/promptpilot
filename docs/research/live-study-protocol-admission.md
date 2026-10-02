# Live-study protocol contract and offline admission

`production_benchmark_protocol.py` defines the versioned declaration required before a
future live production-pipeline adapter can be considered technically configured. It is
an offline validator only. It does not construct providers, make network requests, call
models, create benchmark records, or authorize a live run.

## Offline command

From `apps/backend`:

```powershell
python -m promptpilot_backend.production_benchmark_protocol validate `
  --dataset benchmark_dataset.json `
  --protocol tests/fixtures/production_pipeline/synthetic_protocol.json `
  --output admission-report.json
```

The checked-in example is synthetic and test-only, so the command intentionally writes
`ready=false` and exits nonzero. The output path must not already exist and its parent
must exist. The validator exclusively reserves and probes the output before it loads the
protocol, dataset, manifests, or documents. It never overwrites an earlier report.

## Schema and frozen policies

The strict `v1` model forbids extra fields and is frozen at every nested model boundary.
Lists are represented by tuples. Admission reserializes and revalidates independent
copies so Pydantic `model_copy(update=...)` cannot bypass invariants.

The protocol fixes:

- protocol ID, study title/version, dataset name and canonical dataset hash;
- selected fixture IDs, protocol-relative manifest paths, canonical manifest hashes,
  and review attestations;
- repetitions, question cap, unmatched-gap handling, fallback admission and analysis
  stratum;
- prompt-generation mode and explicit primary/optional secondary evaluation methods;
- provider/model assignment for analysis, questions, prompt generation, both target
  conditions, and a judge only when `llm_judge` is selected;
- exact target parameters for each condition, which must be identical;
- alternating paired order, exact-original-task baseline, task/repetition isolation,
  and prohibition on evaluating incomplete pairs;
- maximum calls by role and in total, optional non-secret monetary metadata, stop rules,
  and locked protocol review metadata.

The target parameter object fixes temperature, maximum tokens, top-p, seed, stop
sequences, presence penalty and frequency penalty. All values are explicit, including
null seed and an empty stop sequence. Unsupported extra parameters fail closed rather
than being silently ignored.

Unresolved placeholders such as `TBD`, `unknown`, or `later` are rejected. Credential-
like field names and values are forbidden recursively, including authorization headers,
bearer values, API keys, tokens, passwords, cookies and secrets. Validation reports use
controlled blocker text and never copy rejected values or raw exception messages.

## Fixture attestations and human boundary

Each selection has a `v1` attestation bound to the fixture ID and canonical manifest
SHA-256. It also declares a reviewer ID, timezone-aware review time, provenance/consent
evidence reference, and whether it is test-only. A test-only attestation can exercise
the schema but cannot admit a live fixture.

Admission calls both existing fixture boundaries: dataset-bound `validate_manifest`
and `admit_live_manifest`. Those functions independently revalidate the manifest,
canonical dataset identity, exact original task and frozen document bytes. Synthetic,
pending, stale, changed or schema-unapproved manifests fail. Attestation identity and
time must match a successfully live-admitted manifest review claim.

These fields are declarations, not proof. The validator cannot establish that the
named reviewer exists, performed the review, had authority, obtained consent, or that
the evidence reference is authentic and sufficient. The report therefore always sets
`human_approval.externally_verified=false`, even when technical readiness is true.
External study governance must verify those claims separately.

## Provider-call ceiling

Let:

- `F` be the number of selected fixtures;
- `R` be repetitions;
- `Q` be the question cap;
- `U = F x R` be the maximum task/repetition units;
- `J = 1` when either configured evaluation method uses `llm_judge`, otherwise `0`.

The conservative ceiling is:

| Role | Maximum calls |
| --- | ---: |
| Analysis | `U` |
| Question generation | `U x Q` |
| Prompt generation | `U` |
| Target execution | `2 x U` |
| Judge | `J x U` |
| Total | `U x (4 + Q + J)` |

The count uses every proposed selected fixture, including one that later produces an
admission blocker. This fail-closed choice prevents a bad fixture from reducing the
budget that will be needed if its evidence is corrected. For a technically ready
protocol, selected and admitted fixture counts are identical. Heuristic reanalysis
after clarification answers is not a provider call.

The checked-in synthetic protocol has one fixture, two repetitions, question cap two,
and heuristic-only evaluation. Its ceiling is analysis 2, question generation 4,
prompt generation 2, target execution 4, judge 0, total 12. Each declared per-role and
total budget must meet or exceed the calculated values.

## Admission report

The machine-readable report includes:

- `ready` and `technical_ready` (currently identical technical gates);
- safe blocker codes/messages and optional fixture/field locations;
- canonical protocol and dataset hashes;
- successfully admitted fixture IDs;
- the calculated call ceiling by role and total;
- the permanent statement that human approval remains externally unverified; and
- the statement that technical admission does not authorize or execute a live study.

Malformed or unsafe protocol data produces a generic fail-closed report without echoing
input values. Dataset, manifest and frozen-document failures likewise use controlled
messages. A false report can be used to correct declarations; it cannot be reinterpreted
as partial authorization.

## Decisions and evidence still required

No checked-in fixture supplies authentic live-study evidence. Before a live adapter can
run, the study owner must provide and externally verify real reviewer identities,
consent/provenance evidence and human-approved manifests. The owner must also choose,
not inherit silently:

- selected tasks/fixtures and repetitions;
- question cap and unmatched-gap behavior;
- whether fallbacks are rejected or admitted only in a separate hybrid stratum;
- primary and optional secondary evaluation methods;
- role-specific providers/models, identical target assignment and exact parameters;
- per-role, total and optional monetary budgets; and
- stop thresholds and protocol reviewer/lock records.

Passing validation means only that a frozen declaration is technically complete and its
repository artifacts agree. A future live runner still needs a separately reviewed
implementation, provider-call ledger, runtime budget enforcement and study-owner
authorization. This validator deliberately provides none of those capabilities.
