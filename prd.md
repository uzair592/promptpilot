# PromptPilot — Product Requirements Document

Repository state: generated from the current HEAD at documentation time. This document
describes the live implementation in the repository, not older README status text.

Current phase: Response Evaluation implemented/audited -> Experimental Dataset Preparation.
The initial dataset and reproducible benchmark harness now exist, but no validated
benchmark results exist yet.

## 1. Product Name

PromptPilot

## 2. Product Vision

PromptPilot is an AI-powered Context Engineering and Prompt Optimization platform. It
understands a user's objective, identifies missing information, gathers relevant context,
structures that context, generates an optimized prompt, executes it against a target LLM,
and evaluates the resulting response.

## 3. Problem

Users often submit incomplete, ambiguous, or context-poor prompts. An LLM can produce a
technically valid answer that is poorly targeted when the objective, requirements,
constraints, audience, project context, supporting documents, or success criteria are
missing. PromptPilot addresses the context-acquisition problem rather than treating
prompt wording alone as the solution.

## 4. Proposed Solution

`User Intent -> Prompt Analysis -> Clarification -> Project Memory -> Document/URL Context -> Retrieval -> Context Assembly -> Prompt Generation -> LLM Execution -> Response Evaluation`

## 5. FYP Objective

Determine experimentally whether PromptPilot improves LLM response quality compared with
directly sending the original prompt to the same target model.

## 6. Target Users

- General AI users
- Students and researchers
- Professionals
- Small-business and project users
- Developers

No market-size or adoption statistics are claimed.

## 7. Core User Journey

1. Register or log in.
2. Create a project.
3. Start a conversation and enter a prompt.
4. Analyze the prompt.
5. Answer clarification questions where needed.
6. Add or use project memory.
7. Upload documents or ingest public URLs.
8. Retrieve and assemble relevant context.
9. Generate an optimized prompt.
10. Execute the baseline and/or PromptPilot prompt.
11. Evaluate responses.
12. Compare results and inspect evaluation history.

## 8. Research Question

When the same target provider and model receive the same original user task, does the
PromptPilot pipeline produce a higher-quality response than direct baseline execution?
The system must measure this question without presuming that PromptPilot wins.

## 9. Success Measurement

Success is measured by paired baseline versus PromptPilot evaluations using the exact
five dimensions:

- Relevance: 25%
- Completeness: 20%
- Instruction Following: 20%
- Contextual Grounding: 20%
- Clarity: 15%

The backend owns the deterministic weighted aggregate. The evaluator and initial
benchmark harness are IMPLEMENTED / RESEARCH-AUDITED, but no validated benchmark
results exist yet.

## 10. Out of Scope

- Autonomous coding or unrestricted agent operation
- Agents, Hermes, browser automation, and tool execution
- Embeddings or semantic retrieval beyond the current lexical baseline
- Production-scale deployment, operations, and enterprise administration
- Claims of improved quality before a validated experiment

## What Exists

- Authentication and session management: Argon2 password hashing, normalized email identity, opaque HTTP-only session cookies, logout, `GET /api/v1/auth/me`, and project-scoped authorization checks.
- Project ownership and roles: `Project`, `ProjectMember`, `ProjectRole` with owner/editor/member permissions and archive enforcement in `require_project_access`.
- Conversation and message persistence: project-scoped conversations, message sequence counters, idempotency-key replay protection, and access control based on project membership.
- Prompt analysis and hybrid AI: baseline heuristic analyzer plus optional `OpenAICompatibleProvider`/AI reconciliation in `analyzer_v2.py`; result includes `overall_score`, status, per-dimension scoring, and `InformationGap` entries.
- Question engine: question sessions, gap prioritization, answer capture, and re-analysis after answer submission; the current generator prefers deterministic fallback and only uses provider questions when provider config is valid.
- Project memory: user answers are stored as active project memory items and superseded on updates. Project memory is used in context assembly and prompt generation.
- Safe document ingestion: supported file types are `.txt`, `.csv`, `.pdf`, `.docx`, `.xlsx`; parsing enforces magic-byte and OOXML validation; URL ingestion rejects localhost/private IPs and redirects beyond configured limits.
- Lexical retrieval and context assembly: `ContextAssembler` ranks memory, answers, and document chunks by task relevance and source authority; duplicate content is de-duped before budget packaging
- Prompt generation and versioning: `PromptGenerationInput` and `PromptVersion` persist optimized prompts with provider/model metadata, generation mode, and source-message provenance.
- Target execution and `ModelRun`: execution supports `baseline` and `promptpilot` strategies, records provider/model/usage, and stores the selected prompt and output alongside a source message.
- Response evaluation and audit (IMPLEMENTED / RESEARCH-AUDITED): heuristic evaluator, LLM judge, five dimensions, deterministic weighted aggregate, neutral A/B judging, same-task/source-message and same provider/model validation, persistence, comparison, frontend comparison/history support, and regression tests.
- Experimental benchmark harness: validated JSON dataset schema with stable task IDs, paired baseline/PromptPilot execution, repeated runs, lineage-preserving exports, and integration with `v1` evaluation. No validated benchmark results exist yet.
- Frontend shell: the Next.js app includes login/register pages, dashboard, project list, project page, conversation workspace, and context preview. It contains the core workspace and implemented controls, while some richer workflow areas remain under development.

### Implemented API surface

- Auth: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`, `GET /api/v1/auth/protected-check`
- Projects: `POST /api/v1/projects`, `GET /api/v1/projects`, `GET /api/v1/projects/{project_id}`, `PATCH /api/v1/projects/{project_id}`, `POST /api/v1/projects/{project_id}/archive`
- Conversations: `POST /api/v1/projects/{project_id}/conversations`, `GET /api/v1/projects/{project_id}/conversations`, `GET /api/v1/conversations/{conversation_id}`, `PATCH /api/v1/conversations/{conversation_id}`, `POST /api/v1/conversations/{conversation_id}/messages`, `GET /api/v1/conversations/{conversation_id}/messages`
- Analysis: `POST /api/v1/conversations/{conversation_id}/messages/{message_id}/analysis`
- Questions: `GET /api/v1/conversations/{conversation_id}/questions/next`, `POST /api/v1/conversations/{conversation_id}/questions/{question_id}/answers`, `POST /api/v1/conversations/{conversation_id}/questions/{question_id}/skip`
- Memory: `GET /api/v1/projects/{project_id}/memory`
- Documents: `POST /api/v1/projects/{project_id}/documents`, `GET /api/v1/projects/{project_id}/documents`, `POST /api/v1/projects/{project_id}/documents/url`
- Context: `POST /api/v1/projects/{project_id}/context/assemble`
- Prompts: `POST /api/v1/conversations/{conversation_id}/prompts/generate`, `POST /api/v1/conversations/{conversation_id}/prompts/{prompt_version_id}/execute`, `GET /api/v1/conversations/{conversation_id}/prompts/runs`
- Evaluations: `POST /api/v1/conversations/{conversation_id}/runs/{run_id}/evaluate`, `POST /api/v1/conversations/{conversation_id}/evaluations`, `POST /api/v1/conversations/{conversation_id}/evaluations/compare`, `GET /api/v1/conversations/{conversation_id}/evaluations`

### Product-level limitations

- This is not an autonomous coding agent; it is a context-engineering and prompt-optimization system with evaluator hooks.
- The repository uses SQLAlchemy models, checked-in SQL migrations under `apps/backend/migrations/`, and SQLite development convenience with `Base.metadata.create_all(...)` where applicable. It does not currently use Alembic; production migration and deployment hardening remain future work.
- LLM provider usage is optional; if `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, or `LLM_API_KEY` are missing, deterministic fallback behavior is used.
- Retrieval is lexical, deterministic, and project-scoped; it is not vector/semantic by default.
- Response evaluation is heuristic by default and explicitly avoids claiming factual verification beyond observable quality metrics.

## PLANNED

- Complete the remaining workspace UI for prompt generation, requirements/export, and evaluation views.
- Add richer project-level model recommendation, task routing, and version history.
- Convert one-off prompt-generation and analysis patterns into stronger domain-specific requirement extraction and acceptance criteria.
- Add human-labelled evaluation data and complete controlled benchmark runs for response quality.
- Add a stricter production schema lifecycle and deployment configuration.

## FUTURE STARTUP

- Multi-model routing across providers plus real usage telemetry and cost/budget controls.
- Embedding-based retrieval, semantic memory, and hybrid retrieval with provenance-aware ranking.
- Agents, Hermes, autonomous coding, browser automation, and a sandboxed execution boundary.
- Full observability, deployment automation, onboarding flows, and enterprise-ready authorization/admin tooling.
- A final FYP experiment and product story built around validated dataset results, not just baseline heuristics.
