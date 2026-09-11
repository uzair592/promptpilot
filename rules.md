# PromptPilot — Rules

Repository state: generated from the current HEAD at documentation time. These rules
reflect the actual live behavior and should be treated as permanent context for future
coding agents.

## Required Agent Workflow

1. Read `prd.md`, `architecture.md`, `rules.md`, `phases.md`, `design.md`, and
   `memory.md` before making changes.
2. Inspect `git status`, `git rev-parse HEAD`, and the relevant implementation before
   editing.
3. Work on one milestone at a time and do not start a later milestone implicitly.
4. Confirm behavior with the smallest relevant existing tests, then run broader checks
   when the change warrants them.
5. Do not report success for a build, test, or benchmark that was not actually run.
6. Do not restart or rewrite the project; preserve the existing modular-monolith
   architecture and do not introduce future-startup features without explicit approval.
7. Do not destroy, reset, discard, or overwrite uncommitted work. Inspect unexpected
   changes and ask before acting if they conflict with the task.
8. Make precise, related changes only. Reuse existing modules and patterns before
   creating new abstractions.
9. Preserve research validity: keep baseline and PromptPilot conditions comparable,
   require same-task/source-message and same provider/model pairing, and never assume
   PromptPilot is better.
10. Commit only related work. Report the exact commit SHA, HEAD, remote alignment,
    working-tree status, files changed, and verification performed.

## IMPLEMENTED

- Treat the repository’s README and roadmap as historical planning docs; do not treat them as current implementation status. The active status is the code in `apps/backend` and the minimal Next.js shell in `apps/frontend`.
- Preserve project authorization: every project/conversation/document operation must validate membership and role before mutation or read access.
- Preserve session integrity: password hashing uses Argon2, session tokens are hashed and stored, cookies are HTTP-only, and invalid or expired sessions must fail closed.
- Do not silently invent facts. The provider-backed analysis, question generation, prompt generation, and retrieval prompts are designed to operate on supplied facts, with fallbacks and provenance metadata.
- Keep provenance visible. `DocumentChunk.provenance`, `ContextCandidate.provenance`, `PromptVersion.metadata_json`, and `ModelRun.usage_json` are part of the audit trail.
- Prefer deterministic fallback before AI. `analyzer_v2.py` runs baseline heuristics first; AI findings are only merged after schema validation, and provider failure falls back without claiming success.
- Treat uploaded content as untrusted input. Safe parsing, file validation, and URL restrictions are required; no code execution on host is permitted.
- Keep the evaluations honest. The actual backend evaluation is a quality heuristic, not a factual verdict. It compares observable response quality using the rubric below and does not claim factual verification beyond the supplied task/context.
- Preserve versioned prompt and run lineage. A `PromptVersion` must always be tied to a source message, and a `ModelRun` must reference project/conversation and optionally the prompt version.
- Keep the question engine bounded. It should ask only from unresolved `InformationGap` items and avoid duplicate question text across a session.
- Do not claim unverified benchmark results. The repo documentation explicitly says the current dataset and retrieval/evaluation baselines are experimental and not yet validated.

### Exact evaluation rubric in the repo

The backend uses these five dimensions and weights:

- `relevance` = 25
- `completeness` = 20
- `instruction_following` = 20
- `contextual_grounding` = 20
- `clarity` = 15

The aggregate is calculated as:

- `weighted_aggregate = round(sum(score * weight for each dimension) / 100, 2)`

The actual dimension order is defined in `schemas.py` as:

- `relevance`
- `completeness`
- `instruction_following`
- `contextual_grounding`
- `clarity`

### Operational constraints

- SQLAlchemy models and checked-in SQL migrations are used with SQLite as a development
  convenience; the project does not currently use Alembic, and production migration and
  deployment hardening are not complete.
- Provider configuration is read from environment variables: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, and request timeout values.
- URL ingestion blocks private or loopback destinations and limits redirect depth and response bytes.
- Prompt generation fails closed when provider output includes unsupported context identifiers.
- `ContextAssembler` enforces a character budget and omits low-priority items rather than exceeding it.

## PLANNED

- Add explicit requirement and acceptance-criteria objects with separate lifecycle states.
- Strengthen policy tests around model selection, access control, and audit completeness.
- Add a benchmark dataset specification and a human-review process for prompt-analysis and retrieval scoring.
- Document the expected migration strategy and production deployment boundary.

## FUTURE STARTUP

- Enforce a full sandbox boundary for tool execution and code generation.
- Replace bounded lexical retrieval with hybrid retrieval and embedding indexes.
- Add agents, Hermes, browser automation, and autonomous coding only after explicit
  approval and appropriate sandboxing.
- Add prompt-generation guardrails, model risk controls, and cost thresholds.
- Create a formal evaluation dataset with labeled ground truth and reproducible benchmark runs.
- Establish production-grade CI/CD, storage, and observability for multi-tenant operations.
