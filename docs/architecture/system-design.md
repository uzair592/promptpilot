# PromptPilot System Design

## Design Goals

PromptPilot remains a modular monolith for the FYP. The frontend is a Next.js client, the backend is a FastAPI application, and PostgreSQL is the source of truth. Domain and application services are framework-independent; adapters handle HTTP, persistence, storage, parsing, and model providers.

## Boundaries

```text
Next.js UI -> REST API -> application use cases -> domain policies
                                      |             |
                                      |             +-> repositories
                                      +-> AI ports -> provider adapters
                                      +-> document ports -> parser/storage adapters
```

The initial backend package should be organized as `api`, `application`, `domain`, `ai`, `documents`, `persistence`, `storage`, `auth`, and `evaluation`. It is intentionally not split into deployable microservices. Long-running parsing and model operations may later use workers behind the same application ports.

## Domain Model Summary

| Entity            | Responsibility                                         | Lifecycle                                   |
| ----------------- | ------------------------------------------------------ | ------------------------------------------- |
| User              | Identity and account status                            | Mutable account; soft disable               |
| Project           | Central ownership and workflow aggregate               | Active, archived, restored                  |
| ProjectMember     | Optional shared access and role                        | Invited, active, removed                    |
| Conversation      | Project-scoped interaction thread                      | Active, archived                            |
| Message           | Immutable authored conversation event                  | Created, retained                           |
| Prompt            | Structured prompt artifact                             | Draft versions, published immutable version |
| PromptAnalysis    | Analysis snapshot and gaps                             | Replaced by new snapshot                    |
| Question / Answer | Adaptive clarification exchange                        | Proposed, answered, skipped, superseded     |
| Document / Chunk  | File metadata and extracted searchable units           | Processing state, retained, deleted         |
| ContextItem       | Source-aware fact, preference, reference, or inference | Proposed, approved, rejected, superseded    |
| Requirement       | Stable, evaluable project requirement                  | Draft, approved, deprecated                 |
| Model             | Capability and availability metadata                   | Registry revisions                          |
| ModelRun          | One provider/model execution                           | Pending, running, succeeded, failed         |
| Evaluation / Item | Response assessment and requirement findings           | Immutable result snapshot                   |
| Task              | Human-facing project planning work item                | Todo, in progress, done, cancelled          |
| GeneratedDocument | Approved-context-based output artifact                 | Draft, published, superseded                |
| ArtifactVersion   | Generic immutable version pointer/metadata             | Created, superseded                         |
| AuditEvent        | Security and AI operation record                       | Append-only                                 |

## Invariants

- A project has an owner and every artifact belongs to exactly one project.
- A conversation belongs to one project and every message belongs to one conversation.
- Authorization is checked before reading metadata, content, or derived artifacts.
- Published prompt, context, requirement, evaluation, and generated-document versions are immutable.
- Context provenance and trust class cannot be silently changed; corrections create a new item/version.
- Requirements keep stable identifiers across revisions so evaluations can refer to them.
- An evaluation refers to one model run and a model run refers to one prompt version.
- Archived projects reject normal mutations until explicitly restored.
- AI inferences are distinguishable from user facts and source-derived facts.
- Uploaded or generated code is data and never executes on the application host.
