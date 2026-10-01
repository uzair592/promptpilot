# Production benchmark fixture contract (v1)

This is the **fixture-validation milestone only**. The manifest is data for a
future production-pipeline adapter; loading it does not create projects, call
providers, ingest documents, or run a benchmark. The existing eight-task
dataset and infrastructure smoke test retain their current behavior.

## Validate offline

From `apps/backend`, after installing the backend development dependencies:

```powershell
python -m promptpilot_backend.benchmark_fixtures validate `
  --dataset benchmark_dataset.json `
  --manifest tests/fixtures/production_pipeline/synthetic_manifest.json
```

The command prints `live_eligible=False` for the included synthetic fixture.
It exits nonzero if the manifest, task identity, source hashes, or frozen
document bytes fail validation. The dataset hash is the canonical
`dataset_sha256(load_dataset(...))` value, not the raw JSON file checksum.
The current value is
`8b7aca964ffae59151a3c8c24a3412823b7d96ff7739d66e9b79ab71648cc53d`.
Any dataset edit requires a new hash and review; task text is checked for an
exact match independently of the hash.
`manifest_sha256` provides a canonical digest of the parsed manifest for
future export lineage, including its declared document checksums.

Loaded manifest fields and nested source collections are immutable. Both
`generation_inputs(manifest, dataset, manifest_path)` and
`admit_live_manifest(manifest, dataset, manifest_path)` revalidate a fresh copy
of the complete declaration against the supplied dataset and frozen document
bytes. This also catches programmatic copies made through Pydantic's
unvalidated `model_copy(update=...)`. The generation projection owns separate
source objects; it does not share mutable references with the manifest.

## Manifest shape

The complete synthetic example is
[`synthetic_manifest.json`](../../apps/backend/tests/fixtures/production_pipeline/synthetic_manifest.json).
Its core fields are:

```json
{
  "schema_version": "v1",
  "fixture_id": "synthetic-planning-workshop-v1",
  "fixture_kind": "synthetic_offline_test",
  "review": {"status": "synthetic", "reviewer_id": null, "reviewed_at": null},
  "dataset_name": "promptpilot-experimental-v1",
  "dataset_sha256": "8b7aca964ffae59151a3c8c24a3412823b7d96ff7739d66e9b79ab71648cc53d",
  "task_id": "planning-launch-001",
  "original_task": {"fixture_id": "original-task", "task_id": "planning-launch-001",
    "source_type": "dataset_original", "content": "<exact dataset task_text>",
    "content_sha256": "<SHA-256 of UTF-8 content>", "provenance": {"source_type": "dataset_original",
    "source_id": "original-task", "description": "Exact dataset source"}},
  "project_facts": [],
  "clarification_answers": [],
  "frozen_documents": [],
  "evaluation_only": []
}
```

Each project fact and clarification answer carries its own source ID, task
reference, source type, provenance and UTF-8 content hash. An answer also has
`gap_key: {"dimension": "audience", "question_target": "Who is the workshop for?"}`.
Matching folds case and whitespace in those two fields, then requires an
exact key match. Duplicate normalized keys are rejected. A gap without a key
match has no fixture answer; an adapter must record it as unanswered or skipped
according to its fixed question policy. It must never infer an answer from a
nearby criterion or another gap. Question wording variation may cause a
legitimate answer to remain unmatched and needs an explicit policy decision.

A frozen document declares a manifest-relative `path`, ingestion `filename`,
`media_type`, source ID, provenance, and SHA-256 of its **raw bytes**. Validation
reads those bytes, rejects path escape, and checks the checksum. Supported
filename and media-type pairs follow the production `ALLOWED_TYPES` mapping. Every
evaluation criterion is a separate `evaluation_only` source with its own
provenance and content hash. The `generation_inputs` projection explicitly
contains only the original task, project facts, clarification answers, and
verified document bytes. Evaluation-only criteria have no field in that type.
The fixture text file is marked `-text` in `.gitattributes` so checkout line
ending conversion cannot change its checksum.

## Admission rules and research boundary

- `synthetic_offline_test` fixtures are ineligible for live experiments,
  regardless of their contents. The included fact, answer and text document
  were invented for offline tests; no reviewer is claimed.
- An `experimental_candidate` stays ineligible while review is `pending`.
  `human_approved` requires a real reviewer ID and review time, and cannot
  include synthetic-test sources. The schema records a review claim; a study
  owner must verify its authenticity and source consent outside this validator.
  `live_eligible` expresses only that schema-level claim. Live technical
  admission must use `admit_live_manifest` with the source dataset; it does
  not prove that the named human performed the review.
- All sources must reference the same known dataset task. Source IDs and gap
  keys must be unique. Unsupported schema versions, source types, document
  types, changed task text, stale dataset hashes, and changed document bytes
  fail admission.
- The validator does not prove fixture facts are true, that an answer addresses
  a future runtime question, or that evaluation criteria are unbiased. Human
  review of each experimental fixture is still required.

Before a live study, fix the fixture review record, question cap and
unmatched/skip policy, fallback admission policy, evaluation method, and model
assignments. Expected heuristic reanalysis after an answer is a production
behavior and **not automatically a provider failure**; any strict AI-backed
completion rule must distinguish it from provider fallback. The future adapter
must expose actual pipeline stages and provider attempts before it can report
full-pipeline evidence. This fixture milestone makes no such claim and leaves
the exact `v1` rubric unchanged.
