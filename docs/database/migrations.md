# Migration Strategy

Use a single ordered migration history owned by the backend. Each migration is forward-only, reviewed, and tested against a disposable PostgreSQL database. Schema changes are never applied by runtime startup in production.

## Proposed Order

1. Extensions, UUID support, timestamps, and users.
2. Projects, members, authorization indexes, and audit events.
3. Conversations and messages.
4. Prompt, prompt versions, analyses, questions, and answers.
5. Documents, chunks, context items, requirements, and sources.
6. Models, model runs, evaluations, and evaluation items.
7. Tasks, generated documents, and generic artifact versions.
8. pgvector extension, embedding metadata, and vector index after retrieval benchmarks.

Use expand-and-contract for incompatible changes. Backfill scripts must be idempotent and separately observable. Destructive cleanup requires a documented retention decision and backup/recovery verification.
