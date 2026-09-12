# PromptPilot — System Architecture

Repository state: generated from the current HEAD at documentation time. This
architecture reflects the actual codebase, not historical README status text.

Current phase: Response Evaluation implemented/audited -> Experimental Dataset Preparation.
The initial dataset and reproducible benchmark harness exist, but no validated benchmark
results exist.

## IMPLEMENTED

### System shape

`Frontend -> FastAPI -> Domain/Application Services -> PostgreSQL-compatible storage (SQLite development convenience) -> LLM Provider abstraction`

- Frontend boundary: Next.js app under `apps/frontend` for login/register, dashboard, project list, project details, conversation workspace, and context preview. It contains the core workspace and implemented controls, while some richer workflow areas remain under development.
- Backend boundary: FastAPI app in `apps/backend/src/promptpilot_backend` with service modules for auth, projects, conversations, analysis, questions, memory, documents, context, prompts, execution, and evaluation.
- Persistence boundary: SQLAlchemy models with PostgreSQL-compatible architecture, checked-in SQL migrations under `apps/backend/migrations/`, and SQLite development convenience where applicable. Dev startup also uses `Base.metadata.create_all(bind=engine)`; the project does not currently use Alembic, and production migration/deployment hardening remains future work.
- AI boundary: `OpenAICompatibleProvider` is the only active provider adapter and is used for analysis, question generation, prompt generation, model execution, and LLM judging when configuration is present.

### Core modules

- `auth.py`: Argon2 password hashing, session token creation, session lookup, revocation.
- `project_policy.py`: project access checks and role ordering (`member < editor < owner`).
- `conversation_service.py`: conversation lifecycle and message insertion with sequence tracking and idempotency.
- `analyzer_service.py`: deterministic baseline scoring for prompt completeness dimensions.
- `analyzer_v2.py`: hybrid reconcile path that runs baseline first, then optional AI reconciliation.
- `question_service.py`: gap prioritization and re-analysis after user answers.
- `memory_service.py`: active project-memory extraction and answer persistence.
- `document_service.py`: safe file parsing, document chunking, and guarded URL fetch/ingest.
- `context_engine.py`: lexical context retrieval and context package assembly with provenance and budget enforcement.
- `prompt_generation.py`: prompt generation input assembly, provider validation, and persisting `PromptVersion` rows.
- `execution_service.py`: executes original or optimized prompts and stores `ModelRun` rows.
- `evaluation_service.py`: deterministic heuristic evaluation plus optional LLM-judge path for response comparison.
- `benchmark.py`: validated task dataset, isolated paired execution, repeated-run records, and JSON/CSV export.

### Data model highlights

- `User`, `SessionToken`, `Project`, `ProjectMember`, `Conversation`, `Message`, `QuestionSession`, `Question`, `Answer`, `ProjectMemoryItem`
- `PromptAnalysis`, `PromptAnalysisDimension`, `InformationGap`
- `Document`, `DocumentChunk`
- `PromptVersion`, `ModelRun`
- `Evaluation`, `EvaluationItem`

Important design constraints:

- `Message.sequence` is unique per conversation.
- `QuestionSession` keeps the latest analysis and active gap status.
- `ProjectMemoryItem` supports superseding older values by setting the previous item to `status="superseded"`.
- `DocumentChunk` retains provenance, chunk index, and processing version.
- `PromptVersion` stores original prompt, optimized prompt, provider/model, and generation metadata.
- `ModelRun` records execution strategy, provider/model, response text, usage JSON, latency, and status.
- `Evaluation` and `EvaluationItem` persist baseline/promptpilot results and per-dimension item explanations.

### Request flow

1. User registers/logs in; cookie-backed session is created.
2. User creates a project and one or more conversations.
3. User message is saved in a project conversation.
4. Baseline analyzer scores completeness and gap status; optional AI may reconcile.
5. Gap questions are created; user answers update project memory.
6. Project memory + answer history + document chunks are assembled into a bounded context package.
7. Prompt generation creates a versioned optimized prompt.
8. Prompt is executed against target model as `baseline` or `promptpilot`.
9. Response is evaluated against task, requirements, constraints, and context.

### Security and safety boundaries

- Session cookies are HTTP-only and `SameSite=Lax`; `verify_password` uses Argon2.
- Authorization is enforced on every project/conversation operation by `require_project_access`.
- URL ingestion only allows public HTTP/HTTPS destinations; localhost/private IP/metadata endpoints are blocked.
- Documents are parsed with user content treated as untrusted; no execution of uploaded or generated code is permitted.
- Prompt-generation code explicitly rejects unsupported context identifiers and never silently invents facts.
- The full AI stack is provider-optional. Missing configuration degrades to baseline behavior rather than silent misreporting.

### Active endpoints

- Auth: `/api/v1/auth/*`
- Projects: `/api/v1/projects*`
- Conversations: `/api/v1/projects/{project_id}/conversations*` and `/api/v1/conversations/{conversation_id}*`
- Analysis: `/api/v1/conversations/{conversation_id}/messages/{message_id}/analysis`
- Questions: `/api/v1/conversations/{conversation_id}/questions/*`
- Memory: `/api/v1/projects/{project_id}/memory`
- Documents: `/api/v1/projects/{project_id}/documents*`
- Context: `/api/v1/projects/{project_id}/context/assemble`
- Prompts: `/api/v1/conversations/{conversation_id}/prompts/*`
- Evaluations: `/api/v1/conversations/{conversation_id}/evaluations*`

### Backend database status

- The repo currently uses SQLAlchemy declarative models and a dev convenience schema creation step.
- Checked-in SQL migrations exist through the model, execution, and evaluation milestones. They are not wired into an Alembic lifecycle.
- SQLite is the default backend for local work; production PostgreSQL migration and deployment hardening remain future work.

## NEXT

- Add human-labelled evaluation data and complete controlled benchmark runs without claiming results in advance.

## PLANNED

- Harden the project membership model with invite, revocation, and audit workflows.
- Introduce richer requirement extraction objects with stable IDs, provenance, and uncertainty states.
- Add a real model recommendation service and routing policy based on task category and cost/latency requirements.
- Add structured end-to-end tests for prompt generation, context assembly, and evaluation against benchmark fixtures.

## FUTURE

- Replace the minimal SQLite/FS storage baseline with durable cloud storage, migration tooling, autoscaling, and observability.
- Add agents, Hermes, autonomous coding, browser automation, and a sandbox boundary for tool execution and code generation.
- Support multi-project, multi-tenant, and enterprise authorization layers.
- Move to a full agentic workflow with planning, execution, evaluation, and safe review loops.
- Package the final evaluation story with completed runs, provenance, and human labels.
