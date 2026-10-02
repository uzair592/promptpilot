# Experimental Dataset and Reproducible Benchmark Harness

## Purpose

This milestone defines a benchmark infrastructure smoke test for paired
direct-task and dataset-template execution. It records paired
model runs and existing `v1` response evaluations without presuming that either
condition will win. The `promptpilot` execution strategy here preserves the
model-run contract; its prompt is built by `default_prompt_builder` from dataset
facts, not by PromptPilot's production context-engineering pipeline. Scores
from this pilot cannot establish the full FYP pipeline's effectiveness.

No validated benchmark results are reported until the dataset and experiment
runs have been completed.

## Dataset

The initial dataset is `apps/backend/benchmark_dataset.json`. It uses stable
task IDs and covers writing, summarization, question answering, extraction,
planning, technical/software, business/professional, and
research/information tasks.

Each item contains:

- `task_id`, `task_text`, and `objective`
- requirements and constraints
- expected output characteristics
- available context
- category and difficulty
- optional reference information

`BenchmarkDataset` validates the schema and rejects duplicate task IDs before
execution.

## Paired conditions

For every task and repetition, the runner creates one isolated project,
conversation, and source user message:

1. **Baseline:** original task -> target provider/model -> response.
2. **Template condition (`promptpilot` strategy):** dataset facts -> optimized prompt artifact -> same target
   provider/model -> response.

Only execution strategy and prompt differ. The source task, project,
conversation, provider, model, and generation parameters are held constant.
Dataset facts are available to the PromptPilot prompt builder, while the
baseline request contains only the original source task. Both responses are
evaluated against the same task facts. The optimized prompt and context are
stored in `PromptVersion` metadata. Each condition is stored as a `ModelRun`
and evaluated through the existing response evaluation service.

## Reproducibility and provenance

Each exported record includes the benchmark task ID, full task facts, source
message, condition run IDs, provider, model, typed generation parameters,
executed prompts, raw responses, usage, finish reasons, latency, context with
dataset-field provenance, evaluation scores and dimension explanations,
evaluation method, rubric version, timestamps, condition order, dataset
version and SHA-256, repository revision when Git is available, deterministic
request hashes, and failures. JSON and CSV exports are supported. Request
hashes canonicalize task facts, condition, provider/model, generation
parameters, the condition's prompt, and its supplied context; secrets are not
inputs. The configured API key is redacted from exports if a provider echoes it.

Generation parameters are stored separately from provider token usage so paired
validation can enforce comparable configuration. Temperature, max tokens, top-p,
and provider-supported options may be recorded; no seed is recorded unless the
provider actually supports and receives one. Condition order uses balanced
alternating execution order by repetition and is persisted for audit. Provider APIs may still be
nondeterministic. Repeated runs are supported for later mean, median, and
variance calculations. This milestone does not implement significance testing.

## Evaluation

The existing `v1` rubric is used without modification:

- relevance: 25
- completeness: 20
- instruction following: 20
- contextual grounding: 20
- clarity: 15

The backend calculates the weighted aggregate. The heuristic evaluator measures
observable response properties and does not make factual-truth claims. LLM
judging receives neutral A/B responses; the randomized mapping is persisted in
`Evaluation.metadata_json` as `judge_assignment`, and scores are mapped back to
baseline and PromptPilot by run ID.

## Valid evidence and limitations

Valid evidence requires a successful paired run with the same target provider,
model, source task, project/conversation, and comparable parameters. Failed
conditions are retained as failed records and are not evaluated as successful
pairs. A single run is not evidence of causal superiority. The current
deterministic template does not run analysis, clarification, memory, retrieval,
context assembly, or production prompt generation. Exported records and
`PromptVersion` metadata label this run as
`benchmark_infrastructure_smoke_test`. Scores are diagnostic for the harness
and template condition only, not evidence for the full FYP pipeline.

## Implemented infrastructure versus results

**Benchmark infrastructure: IMPLEMENTED.** The dataset schema, paired runner,
provenance fields, hashing, exports, evaluation integration, and deterministic
mock tests are implemented.

**Benchmark safety/budget ledger: IMPLEMENTED AND OFFLINE-VALIDATED.** A durable
provider-call ledger binds staged runs to a technically ready admission report and
reserves every provider call atomically before any external invocation. It enforces
exact per-role and total ceilings, idempotent retries, immutable attempt identity,
terminal-state protection, and database-enforced concurrency. It constructs no
provider, stores no credentials, and records external human approval as unverified.

**Controlled live pilot: NOT RUN.** No real provider has been called and no API
credits have been consumed.

**Validated benchmark results: NOT ESTABLISHED.** No real-provider
experiment results or superiority claims are reported. The next research
milestone is a separately designed adapter that runs the production
context-engineering pipeline under a controlled paired protocol, with
appropriate human review and labels. It is outside this smoke test.

**General PromptPilot superiority claim: NOT MADE.** Offline scores from the
smoke test or the ledger cannot support response-quality, statistical, or FYP
effectiveness claims.

## Fixed controlled pilot

The pilot selects the following eight IDs in this fixed order, one from each
category: `writing-email-001`, `summarization-policy-001`,
`qa-geography-001`, `extraction-invoice-001`, `planning-launch-001`,
`technical-api-001`, `business-analysis-001`, and
`research-information-001`. These are the current dataset's sole items in
their categories. The source policy and invoice text are included in their
original task messages so both conditions receive the material required to
perform those tasks. The selection is fixed in `benchmark_pilot.py`; an absent
ID or duplicate category stops the pilot before provider calls. The SHA-256
in the output identifies the selected, normalized dataset snapshot.

Run the offline preflight from `apps/backend`:

```powershell
python -m promptpilot_backend.benchmark_pilot --dataset benchmark_dataset.json --validate-only
```

For a later, explicitly authorized live run, prepare an existing database
with the current schema and an existing owner user. Set these environment
variables in the shell before invoking the command:

- `DATABASE_URL`: database containing the owner and current tables.
- `PILOT_OWNER_ID`: UUID of that existing user.
- `LLM_PROVIDER=openrouter`.
- `LLM_BASE_URL=https://openrouter.ai/api/v1`.
- `LLM_MODEL`: fixed target model identifier for the entire pilot.
- `LLM_API_KEY`: provider credential; keep it out of command arguments and files.
- `LLM_TIMEOUT`: optional positive request timeout in seconds (default 30).

Then, from `apps/backend`, run:

```powershell
python -m promptpilot_backend.benchmark_pilot --dataset benchmark_dataset.json --output-prefix pilot-results --evaluation-method heuristic
```

The command refuses missing or unexpected provider settings, an unknown
owner, missing or unwritable export directories, existing outputs, and
conflicting paths before any target call. Both exports are staged in their
destination directory and published without overwriting existing results. It runs two
repetitions per task in separate projects and conversations: repetition 1
executes baseline then PromptPilot; repetition 2 executes PromptPilot then
baseline. The expected workload is 16 complete pairs and 32 target provider
calls, with `temperature=0` on every target call. Prompt construction is
deterministic from dataset facts: there are **zero** provider calls for
analysis or prompt generation. The default heuristic evaluation makes **zero**
judge calls. Choosing `--evaluation-method llm_judge` would add up to 16
provider calls for judging, one per complete pair. No such calls were made in
the readiness milestone.

Expected outputs are `pilot-results.json` and `pilot-results.csv`, with one
record per task repetition and two condition attempts per complete pair.
Failed attempts and pairs remain in the exports. The command exits nonzero if
fewer than 16 pairs complete. Keep these raw exports private because they
contain task and response text, even though the configured API key is redacted.
Provider variability remains possible despite identical target settings.
