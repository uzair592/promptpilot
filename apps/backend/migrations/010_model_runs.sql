CREATE TABLE IF NOT EXISTS model_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    prompt_version_id uuid REFERENCES prompt_versions(id) ON DELETE SET NULL,
    source_message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    execution_strategy varchar(20) NOT NULL CHECK (execution_strategy IN ('baseline', 'promptpilot')),
    optimized_prompt text NOT NULL,
    response_text text,
    provider varchar(80) NOT NULL,
    model varchar(160) NOT NULL,
    status varchar(20) NOT NULL,
    finish_reason varchar(80),
    usage_json text NOT NULL DEFAULT '{}',
    latency_ms integer,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_model_runs_conversation_created ON model_runs (conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_model_runs_project_created ON model_runs (project_id, created_at DESC);
