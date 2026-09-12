# PromptPilot — Product and Technical Design

Repository state: generated from the current HEAD at documentation time. This is the
implementation design as it exists in code today, not the aspirational roadmap.

## 1. Product Experience

PromptPilot should feel familiar like an AI chat application while guiding the user
through context engineering. Internal complexity is progressively disclosed rather than
shown all at once.

## 2. Main Workspace

The current workspace combines conversation, prompt analysis, clarification, memory and
context preview, generated prompts, target execution, and evaluation/comparison history.
Some deeper modules remain intentionally minimal or placeholder UI.

## 3. UX Principles

- Show simple controls first; expose provenance and scoring details on demand.
- Always distinguish Original Prompt from Optimized Prompt.
- Always distinguish Baseline from PromptPilot.
- Never show a winner or improvement claim before evaluation data exists.
- Keep errors understandable, truthful, actionable, and non-sensitive.
- Give AI operations clear loading and failure states.

## 4. Accessibility and Visual Direction

Use readable typography, semantic controls, keyboard-accessible actions, descriptive
states, and clear contrast. The visual direction is clean, modern, professional, minimal,
and familiar without copying a proprietary interface.

## IMPLEMENTED

### Identity and authorization model

- `User` stores `email`, normalized email, display name, password hash, status, and timestamps.
- `SessionToken` stores a hashed opaque token and expiry; `get_user_by_session` validates expiry and user activity.
- `ProjectMember` controls project role membership and `ProjectRole` order is `member < editor < owner`.
- `require_project_access` rejects missing membership and enforces archived-project restrictions.

### Conversation and message model

- `Conversation` is owned by a project and tracks active/archived status.
- `ConversationMessageCounter` assigns a unique sequence per conversation.
- `Message` stores role, content, sequence, and idempotency key. Idempotent retries for a message in the same conversation return the existing row.

### Prompt analysis and question model

- `PromptAnalysis` persists task category, score, status, version, mode, provider/model metadata, and dimension/gap entries.
- `PromptAnalysisDimension` stores the per-dimension score and explanation.
- `InformationGap` stores severity, importance, and the question target.
- `QuestionSession` tracks a gap-driven session; `Question` stores generated question text, priority, status, and answer references.
- `Answer` stores user answers; `ProjectMemoryService` stores them as active memory.

### Document and retrieval model

- `Document` stores metadata including checksum, size, status, error message, source URL, and version.
- `DocumentChunk` stores chunk text, provenance, size, and processing version.
- `ContextAssembler` builds a `ContextPackage` from project memory, user answers, document context, and unresolved analysis constraints.
- `LexicalContextRetriever` tokenizes the task and computes overlap against document chunks; it then sorts by score and returns the top `k` chunks.
- The context package enforces a budget and de-dupes identical content. Low-priority items are omitted rather than exceeding the budget.

### Prompt generation model

- Modes: `structured`, `minimal`, `detailed`.
- `PromptGenerationInput` enforces the selected generation mode and uses the assembled context package plus relevant answers and requirements.
- `PromptGenerator.generate()` validates the provider’s response against supported context IDs and rejects empty or malformed prompts.
- `persist_generation()` creates a `PromptVersion` row with the original prompt, optimized prompt, generation metadata, and provider/model fields.

### Model execution model

- `LLMExecutionService.execute()` supports `baseline` and `promptpilot` strategies.
- `baseline` executes the original user prompt.
- `promptpilot` executes the optimized prompt stored in `PromptVersion`.
- `ModelRun` stores response text, finish reason, usage JSON, latency, provider/model, execution strategy, and errors when they occur.

### Evaluation model

The actual evaluator is defined in `schemas.py` and enforced in `evaluation_service.py`.

- Dimensions: `relevance`, `completeness`, `instruction_following`, `contextual_grounding`, `clarity`
- Weights:
  - `relevance`: 25
  - `completeness`: 20
  - `instruction_following`: 20
  - `contextual_grounding`: 20
  - `clarity`: 15
- Weighted aggregate: `sum(score * weight) / 100`, rounded to 2 decimal places.
- `ResponseEvaluationService` supports `heuristic` and `llm_judge` methods.
- `evaluate_pair()` compares baseline and promptpilot runs, stores `overall_delta`, and records winner and item-level explanations.
- `EvaluationItem` persists five item records per response for the five dimensions in the comparison or single-run evaluation.

### Actual limitations in the current implementation

- The header/process is a deterministic baseline, not a production-grade agentic optimizer.
- Retrieval is lexical; there is no vector database layer or embedding retrieval at this HEAD.
- Document ingestion supports a fixed allowlist and public-URL restrictions; it does not generalize to arbitrary file types or private network destinations.
- `OpenAICompatibleProvider` is the only active provider adapter and it reads config from environment variables.
- Checked-in SQL migrations exist under `apps/backend/migrations`; local development
  additionally creates the SQLAlchemy schema at startup.
- The app does not implement autonomous tool execution, sandbox traversal, or a true planning engine.

## PLANNED

- Add stable requirement objects with explicit lifecycle states and dependency metadata.
- Add a real model-router service based on task category and performance metadata.
- Add human-labeled gold sets, controlled benchmark runs, and regression fixtures to the initial benchmark harness.
- Improve the frontend to show prompt generation, run history, requirement extraction, and evaluation results in one workspace.

## FUTURE

- Hybrid retrieval with embeddings, filters, and reranking.
- Provider abstraction and routing beyond the single OpenAI-compatible adapter.
- Agents, Hermes, autonomous coding, and browser automation behind explicit approval and sandbox boundaries.
- Storage, deployment, and operational controls for production-scale usage.
- A full software planning and execution pipeline anchored by audited context, prompt versions, model runs, and evaluation records.
