# Domain Model

## Core Entities

- `User`: identity and account status.
- `Project`: central aggregate, owner, metadata, lifecycle, and current versions.
- `Conversation`: project-scoped interaction thread.
- `Message`: authored conversational content with role and timestamp.
- `TaskProfile`: classified task/domain and capability needs.
- `PromptAnalysis`: dimensions, score, status, gaps, and explanation.
- `Question` and `Answer`: prioritized clarification exchange with status and provenance.
- `FileAsset` and `DocumentExtraction`: stored object metadata and parser output.
- `ContextItem` and `ContextPackage`: source-linked facts, inferences, references, and bounded assembled context.
- `Requirement`: stable ID, type, statement, status, source, priority, and uncertainty.
- `PromptVersion`: structured generated instruction package and source version references.
- `ModelRecommendation` and `ModelRun`: ranked options and execution metadata.
- `ResponseEvaluation`: overall result, per-requirement findings, gaps, uncertainty, and recommendations.
- `GeneratedDocument`: approved-context-based planning artifact and version.
- `AuditEvent`: actor, operation, target, timestamp, and safe metadata.

## Invariants

- Every project artifact belongs to exactly one project.
- A user may access artifacts only through project authorization.
- Versions are immutable records; new changes create a new version.
- AI inferences never masquerade as user facts.
- Requirement and evaluation findings reference stable requirement IDs.
- Binary content is stored outside PostgreSQL; metadata and references remain in PostgreSQL.
