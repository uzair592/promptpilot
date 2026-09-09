CREATE TABLE IF NOT EXISTS prompt_analyses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    task_category varchar(40) NOT NULL,
    overall_score integer NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
    status varchar(20) NOT NULL CHECK (status IN ('Poor', 'Medium', 'Good')),
    analysis_version varchar(40) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prompt_analyses_message_created ON prompt_analyses (message_id, created_at DESC);

CREATE TABLE IF NOT EXISTS prompt_analysis_dimensions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id uuid NOT NULL REFERENCES prompt_analyses(id) ON DELETE CASCADE,
    key varchar(40) NOT NULL,
    score integer CHECK (score BETWEEN 0 AND 100),
    status varchar(20) NOT NULL,
    applicable boolean NOT NULL,
    evidence text,
    explanation text NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_prompt_analysis_dimensions_analysis ON prompt_analysis_dimensions (analysis_id);

CREATE TABLE IF NOT EXISTS information_gaps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id uuid NOT NULL REFERENCES prompt_analyses(id) ON DELETE CASCADE,
    dimension varchar(40) NOT NULL,
    title varchar(160) NOT NULL,
    description text NOT NULL,
    severity varchar(20) NOT NULL CHECK (severity IN ('critical', 'important', 'optional')),
    importance varchar(20) NOT NULL,
    question_target text NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'unresolved'
);
CREATE INDEX IF NOT EXISTS ix_information_gaps_analysis_severity ON information_gaps (analysis_id, severity);
