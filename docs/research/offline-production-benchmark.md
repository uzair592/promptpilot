# Offline production-pipeline benchmark runner

`production_benchmark_offline.OfflinePipelineBenchmark` is a Python API for
**synthetic, offline fixture tests** of the production service sequence. It has
no CLI or live-provider entry point. Every provider must be passed explicitly
and marked `offline_fixture=True`; the live `OpenAICompatibleProvider` is
rejected. This is not an approved live study protocol and produces no evidence
of PromptPilot performance with a live model.

## Inputs and fixed policy

Call `run(db, dataset, manifest_paths, owner_id, repetitions, policy,
output_dir)` with a pre-existing active owner, a validated dataset, and paths
to fixture manifests. The runner reloads each fixture through the
dataset-bound validator and generation-input projection before use. The
included test fixture is synthetic and is admitted only because the execution
mode is fixed to `offline_fixture`. It cannot be used as a human-reviewed live
fixture.

`OfflinePolicy` requires all of these values explicitly:

| Field | Supported offline values |
| --- | --- |
| `question_cap` | Integer from 0 to 50; at the cap, no further provider question is requested. |
| `unmatched_gap` | `stop` or `skip`; neither fabricates an answer or permits a complete pair with a missing answer. |
| `fallback` | `reject` or `allow`; allowed fallbacks remain visible in the stage ledger. |
| `generation_mode` | `structured`, `minimal`, or `detailed`. |
| `evaluation_method` | `heuristic` or `llm_judge`; judging requires an injected offline judge. |
| `model_parameters` | Exact target parameters applied to both conditions; credential fields are rejected. |

The runner uses `create_project`, `create_conversation`, and `add_message` for
each task/repetition; confirms active owner membership; adds fixture facts via
`ProjectMemoryService`; ingests frozen document bytes through
`DocumentService`; calls `analyze_hybrid`, shared question services,
`reanalyze_after_answer`, `build_generation_input`, `PromptGenerator`,
`persist_generation`, `LLMExecutionService`, and `ResponseEvaluationService`.
The baseline executes the original task, and target order alternates by
repetition. Evaluation-only criteria enter evaluation after both target runs;
they do not enter the production generation input. The `v1` rubric and
backend-owned aggregate are unchanged.

## Checkpoints and outputs

`output_dir` must not exist and its parent must exist. The runner creates and
probes it before any provider call. It writes exclusive, append-only
`<task-id>-r<repetition>-<sequence>.json` checkpoints as a unit progresses,
then exclusive `results.json` and `results.csv` files. Existing results are
never overwritten. Both final exports include complete, partial, and failed
units. CSV fields `policy`, `stage_ledger`, `provider_observations`, and
`artifacts` contain JSON so raw prompts, responses, IDs, selected/omitted
context, evaluation items, ordering, and failures remain available there as
well as in JSON.

All records use `experiment_scope=production_pipeline_paired_v1` and
`execution_mode=offline_fixture`. A complete pair requires the persisted
production prompt version, two succeeded same-source and same-model target
runs with identical parameters, successful `v1` evaluation, no missing fixture
answers, and every required provider observation. An observer callback error
is swallowed by product services but leaves a missing observation; the runner
marks that unit failed instead of claiming a complete evidence record.
Provider exceptions are exported by type only. Known credential values and
authorization-header text are redacted from every checkpoint and final export.

Expected `reanalyze_after_answer` is recorded as heuristic reanalysis with no
provider call. Analysis/question provider failures, deterministic fallbacks,
and duplicate-question fallback remain distinct observations. The runner
stops treatment preparation on missing answers or a rejected fallback; failed
target attempts and any already persisted raw run remain visible.

## Before a live study

Human fixture review and consent, stable gap/question policy, fallback
admission, question cap, evaluation method, model assignments, budgets, and
the analysis stratum must be fixed and documented. A later live adapter needs
its own entry point, approved manifest admission, durable provider-call ledger
and failure policy, plus review of full pipeline results. Offline scores from
this runner cannot support superiority or full FYP effectiveness claims.

The durable technical ledger is now implemented separately and documented in
[benchmark-provider-call-ledger.md](benchmark-provider-call-ledger.md). It enforces
admitted bindings and call ceilings but does not turn this offline runner into a live
runner or establish external approval.
