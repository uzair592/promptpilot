CREATE TABLE IF NOT EXISTS prompt_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    source_message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    analysis_id uuid REFERENCES prompt_analyses(id) ON DELETE SET NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    original_prompt text NOT NULL,
    optimized_prompt text NOT NULL,
    generation_mode varchar(20) NOT NULL,
    provider varchar(80) NOT NULL,
    model varchar(160) NOT NULL,
    fallback_used boolean NOT NULL DEFAULT false,
    metadata_json text NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, version_number)
);
CREATE INDEX IF NOT EXISTS ix_prompt_versions_conversation_created ON prompt_versions (conversation_id, created_at DESC);
