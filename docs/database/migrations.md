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

The currently implemented migration sequence is `001_users_and_sessions.sql`, `002_projects_and_memberships.sql`, and `003_conversations_and_messages.sql`. The third migration creates only conversations and messages. Message ordering uses a unique per-conversation integer sequence and optional per-conversation idempotency key.

Use expand-and-contract for incompatible changes. Backfill scripts must be idempotent and separately observable. Destructive cleanup requires a documented retention decision and backup/recovery verification.
Migration `003_conversations_and_messages.sql` also creates `conversation_message_counters` and backfills each counter from existing message sequences. Message inserts lock the counter row, preserving unique deterministic ordering under concurrent PostgreSQL transactions.

Migration `004_prompt_analyzer.sql` creates historical prompt analysis, dimension, and information-gap tables. Analyses are append-only records and reference the authorized project, conversation, and source message.
