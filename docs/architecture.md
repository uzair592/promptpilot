# Architecture

The implemented FYP core follows:

`USER INTENT -> ANALYSIS -> QUESTIONS -> ANSWERS -> MEMORY -> RETRIEVAL -> CONTEXT ASSEMBLY -> PROMPT GENERATION -> PROMPT VERSION`

Prompt generation is the first stage that turns assembled project context into an
executable optimized prompt. Autonomous coding, deployment, agents, evaluation,
embeddings, and vector search remain future startup capabilities.

## Shape

PromptPilot is a modular monorepo with a Next.js frontend boundary, a Python/FastAPI backend boundary, a shared contracts package, and documentation/test infrastructure. The backend follows dependency inversion: HTTP and persistence depend on application use cases; domain logic depends on interfaces, not frameworks or vendors.

```text
Frontend (Next.js)
        |
        v
API / transport adapters (FastAPI)
        |
        v
Application use cases
        |
        +--> Domain models and policies
        +--> AI orchestration ports --> replaceable provider adapters
        +--> Document processing ports
        +--> Persistence ports --> PostgreSQL / pgvector
        +--> File storage ports --> local storage / S3-compatible storage
        +--> Evaluation services
```

## Backend Boundaries

- `api`: authentication, request validation, serialization, error mapping.
- `application`: use cases and transaction-level orchestration.
- `domain`: project, conversation, context, requirement, prompt, evaluation, task, and version rules.
- `ai`: orchestration and ports for `LLMProvider`, `EmbeddingProvider`, `ContextRetriever`, `PromptAnalyzer`, `QuestionGenerator`, `RequirementExtractor`, `PromptGenerator`, `ResponseEvaluator`, and `ModelRouter`.
- `documents`: safe file validation, parsing, extraction, chunking, and metadata.
- `persistence`: repositories, migrations, PostgreSQL, and vector search implementation.
- `storage`: file-storage interface and local implementation first.
- `auth`: identity, authorization, and project ownership checks.
- `evaluation`: experiment fixtures, scoring, and reporting.

## Data and Storage

PostgreSQL is the source of truth. UUID identifiers, UTC timestamps, foreign keys, unique constraints, and query indexes are required. Large binaries remain outside PostgreSQL behind a storage abstraction; database rows retain metadata and object references. pgvector is introduced when context retrieval is implemented.

## AI Provider Model

Application services consume stable interfaces. Adapters translate provider-specific requests and responses into internal models. Provider names, models, prompts, and credentials are configuration; secrets are environment-managed. AI runs record provider/model metadata and enough normalized input/output information for audit and evaluation without exposing protected system prompts.

## Security Boundaries

Validate inputs at the API boundary and again at security-sensitive service boundaries. Enforce file type and size limits, parse documents in controlled libraries, treat uploaded text as untrusted data, isolate system instructions from user content, and never execute uploaded or generated code on the host. Future execution requires a sandbox boundary.

## Testing Strategy

Domain and application services use unit tests with fake ports. FastAPI routes use integration tests against an isolated database or test repository. Frontend components use unit/component tests. Critical user workflows receive end-to-end coverage. AI evaluation uses versioned fixtures, mocked providers, and explicit human-review criteria.

## Change Rule

A feature should arrive as a vertical slice: contract, domain/application behavior, adapter, persistence, API, UI, tests, and documentation. Architectural changes require an ADR.

## Detailed Design

See [system design](architecture/system-design.md), [database design](database/database-design.md), [API design](api/api-design.md), [AI pipeline](ai/ai-pipeline.md), [security architecture](architecture/security-architecture.md), and [test architecture](testing/test-architecture.md) for implementation-level contracts.
