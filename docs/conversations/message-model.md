# Message Model

Messages contain `id`, `conversation_id`, `role`, `content`, `sequence`, `idempotency_key`, and `created_at`. Roles are restricted to `user`, `assistant`, and `system`. Content is append-oriented and has no edit/delete endpoint in this slice.

Messages are returned in ascending `sequence` order. The `(conversation_id, sequence)` uniqueness constraint prevents duplicate order values. An optional `Idempotency-Key` maps retries to the original message through `(conversation_id, idempotency_key)` uniqueness.

This slice stores messages only. It does not call a model or generate assistant content.
