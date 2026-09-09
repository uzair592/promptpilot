CREATE TABLE IF NOT EXISTS question_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    analysis_id uuid NOT NULL REFERENCES prompt_analyses(id) ON DELETE CASCADE,
    latest_analysis_id uuid REFERENCES prompt_analyses(id) ON DELETE SET NULL,
    status varchar(20) NOT NULL DEFAULT 'active', stop_reason varchar(80),
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), session_id uuid NOT NULL REFERENCES question_sessions(id) ON DELETE CASCADE,
    gap_id uuid NOT NULL REFERENCES information_gaps(id) ON DELETE CASCADE, text text NOT NULL,
    question_type varchar(20) NOT NULL CHECK (question_type IN ('free_text','single_choice','multi_choice')),
    source varchar(20) NOT NULL DEFAULT 'fallback', options text,
    priority integer NOT NULL, status varchar(20) NOT NULL DEFAULT 'generated', created_at timestamptz NOT NULL DEFAULT now(), answered_at timestamptz
);
CREATE INDEX IF NOT EXISTS ix_questions_session_status ON questions (session_id, status, priority DESC);
CREATE TABLE IF NOT EXISTS answers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    content text NOT NULL, source varchar(30) NOT NULL DEFAULT 'user', created_at timestamptz NOT NULL DEFAULT now()
);
