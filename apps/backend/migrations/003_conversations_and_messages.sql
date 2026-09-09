-- PromptPilot conversational storage slice. PostgreSQL 15+.
CREATE TABLE IF NOT EXISTS conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title varchar(160) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_conversations_status CHECK (status IN ('active', 'archived'))
);

CREATE INDEX IF NOT EXISTS ix_conversations_project_updated
    ON conversations (project_id, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role varchar(20) NOT NULL,
    content text NOT NULL,
    sequence integer NOT NULL,
    idempotency_key varchar(128),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_messages_conversation_idempotency UNIQUE (conversation_id, idempotency_key),
    CONSTRAINT uq_messages_conversation_sequence UNIQUE (conversation_id, sequence),
    CONSTRAINT ck_messages_role CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE INDEX IF NOT EXISTS ix_messages_conversation_sequence
    ON messages (conversation_id, sequence ASC);
