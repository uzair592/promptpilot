# PromptPilot — Project Memory

Repository state: generated from the current HEAD at documentation time. This file
describes the live memory model used by the code, not old aspirational design text.

## 1. Project Origin

PromptPilot began as a prompt-quality and prompt-meter concept and evolved into a
Context Engineering and Prompt Optimization platform. `Project` became the central
domain because prompts exist within conversations, memory, documents, versions,
executions, and evaluations.

## 2. Core Product Evolution

`Prompt Analysis -> Context Collection -> Context Engineering -> Prompt Generation -> Execution -> Evaluation`

## 3. Important Decisions

- Modular monolith rather than microservices for FYP complexity and maintainability.
- A provider abstraction for model flexibility, with OpenRouter as the current cloud gateway.
- Lexical retrieval first because it is deterministic and inspectable.
- Backend-owned evaluation aggregates for reproducibility.
- Same-task/source-message and same-model pairing as a mandatory fair comparison condition.
- Neutral A/B labels to reduce evaluator bias.
- Project-centered rather than standalone prompt-rewrite workflows.
- Agents and Hermes are future-startup scope, not current architecture.

## IMPLEMENTED

### Project memory

- `ProjectMemoryItem` stores the user-facing memory of a project in a simple durable table.
- Fields: `project_id`, `category`, `subject`, `content`, `source`, `status`, `confidence`, `created_at`, `updated_at`.
- `ProjectMemoryService.add_user_answer()` creates a new active memory item and supersedes any prior active item with the same `subject`.
- `ProjectMemoryService.active()` returns only active memory rows for a project, ordered by creation time.

### User answers and question memory

- `QuestionSession` is the lifecycle object for a gap-driven questioning loop.
- `Question` stores the generated question, priority, status, and the `gap_id` that triggered it.
- `Answer` stores the user’s response text and the user origin.
- After a question is answered, `reanalyze_after_answer()` re-runs the analysis for the same message using project memory and prior answers.

### Context package

`ContextAssembler` creates a dynamic package rather than storing a second tier of long-lived memory.

- Project memory is added as `memory` candidates.
- User answers are added as `answer` candidates.
- Document chunks are added as `document` candidates via the lexical retriever.
- Unresolved analysis constraints are added as `constraint` candidates when they match the current task.
- Candidates are ranked by task relevance and source authority, then de-duped and budget-limited.
- Final output includes:
  - `project_memory`
  - `user_answers`
  - `document_context`
  - `requirements`
  - `constraints`
  - `sources`
  - `omitted_items`
  - `budget`
  - `used_budget`

### Retrieval semantics

- `LexicalContextRetriever.retrieve()` tokenizes both the task and document text.
- Relevance is based on task-term overlap and phrase hits.
- Source authority is fixed by source type:
  - requirement = 1.0
  - constraint = 1.0
  - memory = 0.88
  - answer = 0.82
  - document = 0.72
- The result is project-scoped and provenance-preserving; every selected document chunk keeps a document identifier, chunk identifier, and provenance string.

### Prompt versioning and audit trail

- `PromptVersion` stores the original prompt and the optimized prompt, the provider/model used, generation mode, and metadata JSON.
- `ModelRun` records executed prompt, response, strategy, usage JSON, provider/model, and latency.
- `Evaluation` persists the response comparison or single-run evaluation, plus item-level dimension scores and explanations.

### Actual memory-related limitations

- The current system is not a full long-term memory graph or vector memory store.
- Project memory is intentionally simple and shallow; it is not policy-agnostic or automatically summarized beyond the active item list.
- Document retrieval is lexical-only and does not use embeddings or document summarization at this HEAD.
- Context assembly is dynamic and derived from current state; it is not a persisted “memory snapshot” independent of the message and document state.

### Lessons learned

- The AI analyzer previously returned the baseline result after a successful AI response;
  the reconciliation path was corrected to retain the validated AI result.
- Question generation initially lacked sufficient context, so task and analysis evidence
  now accompany provider-backed question generation.
- The context assembler initially omitted complete source categories and was corrected to
  include memory, answers, requirements, constraints, and document context.
- URL size enforcement initially happened after buffering; bounded reads now enforce the
  limit during ingestion.
- Office-file validation initially needed strengthening; supported OOXML inputs now
  receive stronger validation.
- Evaluation initially used incorrect dimensions and was corrected to the exact five
  research dimensions and weights.
- Paired evaluation initially lacked source-message matching; same-task/source-message
  validation is now mandatory.
- The experimental benchmark foundation validates stable task IDs, isolates each
  repeated task pair in its own project/conversation, preserves model parameters in
  run metadata, and exports raw records without claiming results.

## PLANNED

- Add requirement memory with stable IDs and explicit status transitions.
- Add overlap-detection for repeated questions and memory conflicts.
- Add a richer provenance log for answer-to-requirement-to-prompt lineage.
- Add support for semantic retrieval and hybrid ranking.

## FUTURE STARTUP

- Multi-project semantic memory, retrieval caches, and long-term user state.
- Policy-aware memory scoping for authorization, compliance, and retention.
- Full task-graph memory with structured causal/reasoning traces.
- Human-labelled evaluation data, controlled run reporting, and memory regressions tied
  to prompt versions and model runs.
