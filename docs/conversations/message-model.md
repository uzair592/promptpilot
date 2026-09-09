# Message Model

Messages contain `id`, `conversation_id`, `role`, `content`, `sequence`, `idempotency_key`, and `created_at`. Roles are restricted to `user`, `assistant`, and `system`. Content is append-oriented and has no edit/delete endpoint in this slice.

Messages are returned in ascending `sequence` order. Each conversation has a database-backed counter row locked with `SELECT ... FOR UPDATE` while a message is created. The `(conversation_id, sequence)` uniqueness constraint remains a final integrity guard. An optional `Idempotency-Key` maps retries to the original message through `(conversation_id, idempotency_key)` uniqueness; an integrity-conflict retry returns the already-committed message.

Creating a message updates the parent conversation's `updated_at` in the same transaction, so recent conversations sort first. Conversation and message list totals are database `COUNT(*)` queries. The API cursor is an opaque base64-encoded offset (not keyset pagination), bounded to one million rows.

This slice stores messages only. It does not call a model or generate assistant content.
