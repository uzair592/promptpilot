# Experimental Dataset and Reproducible Benchmark Harness

## Purpose

This milestone defines the first research-grade raw-data pipeline for comparing
direct target-model execution with PromptPilot execution. It records paired
model runs and existing `v1` response evaluations without presuming that either
condition will win.

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
2. **PromptPilot:** dataset facts -> optimized prompt artifact -> same target
   provider/model -> response.

Only execution strategy and prompt differ. The source task, project,
conversation, provider, model, generation parameters, and available context are
held constant. The optimized prompt and context are stored in `PromptVersion`
metadata. Each condition is stored as a `ModelRun` and evaluated through the
existing response evaluation service.

## Reproducibility

Each exported record includes the benchmark task ID, source message, condition
run IDs, provider, model, parameters, optimized prompt, assembled context,
evaluation method, rubric version, timestamps, order, and errors. JSON and CSV
exports are supported.

The backend stores generation parameters alongside usage metadata so paired-run
validation can enforce comparable parameters. Provider APIs may be
nondeterministic; no seed is invented when a provider does not support one.
Repeated runs are supported for later mean, median, and variance calculations.
This milestone does not implement significance testing.

## Evaluation

The existing `v1` rubric is used without modification:

- relevance: 25
- completeness: 20
- instruction following: 20
- contextual grounding: 20
- clarity: 15

The backend calculates the weighted aggregate. The heuristic evaluator measures
observable response properties and does not make factual-truth claims. LLM
judging retains neutral A/B evidence and maps scores back to baseline and
PromptPilot using the existing audited service.

## Valid evidence and limitations

Valid evidence requires a successful paired run with the same target provider,
model, source task, project/conversation, and comparable parameters. Failed
conditions are retained as failed records and are not evaluated as successful
pairs. A single run is not evidence of causal superiority. The initial
optimized prompt builder is deliberately transparent and dataset-driven; it is
not an autonomous agent, embedding retriever, or production experiment
orchestrator.

Later work may add human labels, richer context fixtures, statistical
summaries, and controlled provider-specific reproducibility metadata.
