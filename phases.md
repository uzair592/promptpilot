# PromptPilot — Phases

Repository state: generated from the current HEAD at documentation time. This phase
record reflects repository reality rather than historical roadmap text.

Current phase: Response Evaluation implemented/audited -> Experimental Dataset Preparation.
This repo contains an initial validated dataset schema and reproducible paired runner,
but no validated benchmark results or final performance claims.

## COMPLETE

### Phase A: foundation and identity

- Monorepo structure and Python backend/Next.js frontend boundary.
- Version metadata and package basics (`__version__ = "0.1.0"`).
- Authentication, password hashing, session management, and project membership checks.

### Phase B: project and conversation operations

- Project creation, listing, updating, archival, and role-based access.
- Conversation creation, listing, message persistence, and idempotency-key replay prevention.
- Conversation access control using project ownership/role semantics.

### Phase C: prompt analysis and questioning

- Baseline prompt analyzer with dimensions: intent, objective, requirements, context, constraints, output, audience, success_criteria, ambiguity.
- Hybrid analysis mode that applies AI reconciliation only after structured validation.
- Question sessions, gap prioritization, answer ingestion, and re-analysis after user answers.

### Phase D: memory, documents, and retrieval

- Project memory for user answers and active facts.
- Supported file ingestion for `.txt`, `.csv`, `.pdf`, `.docx`, and `.xlsx`.
- Safe URL ingestion restricted to public HTTP/HTTPS destinations and bounded size/redirect checks.
- Lexical retrieval using task-term overlap and source authority with budget-aware context assembly.

### Phase E: prompt generation and execution

- Generation modes: `structured`, `minimal`, `detailed`.
- Versioned prompt artifacts stored as `PromptVersion` rows.
- Target execution support for baseline vs promptpilot strategies and persisted `ModelRun` rows.

### Phase F: target execution

- Target model execution, baseline execution, PromptPilot execution, and persisted `ModelRun` records.

## IMPLEMENTED / AUDITED

### Response Evaluation

- Heuristic evaluator and LLM judge across the exact five research dimensions.
- Deterministic weighted aggregate owned by the backend.
- Neutral A/B judging, same-task/source-message validation, and same provider/model validation.
- Evaluation persistence, baseline-vs-PromptPilot comparison, frontend comparison/history support, and regression tests.
- Status: IMPLEMENTED / RESEARCH-AUDITED. The benchmark foundation now exists, but no validated results exist yet.

### Experimental Dataset + Benchmark Harness

- Initial curated dataset spans eight task categories with stable IDs and structured task facts.
- `benchmark.py` executes isolated repeated baseline/PromptPilot pairs through the existing provider, model-run, and `v1` evaluation services.
- JSON and CSV exports preserve task, prompt, context, model parameters, lineage, evaluation, ordering, timestamps, and failures.
- Status: IMPLEMENTED FOUNDATION. No validated benchmark results exist yet.

### Phase G: minimal product shell

- Full auth flow and dashboard/project shell in the frontend.
- Conversation workspace and context preview page.
- Remaining feature modules are intentionally placeholders until backend features are finalized.

## NEXT

- Human-labelled evaluation data where appropriate.
- Controlled benchmark execution and reporting.

## PLANNED

- A complete frontend around prompt generation, evaluation history, and document review.
- Better requirement extraction and project-planning artifacts derived from approved context.
- More robust model recommendation and usage metadata reporting.
- Production database migration and deployment workflow.

## FUTURE

- Embedding-based and hybrid retrieval.
- Model routing, budgeting, and measurable cost/performance trade-offs.
- Agents, Hermes, autonomous task/coding execution, browser automation, sandboxing, and approval gates.
- Final FYP dataset/reporting with evidence, human judgments, and reproducible benchmark results.
- Production operations, observability, and enterprise security controls.
