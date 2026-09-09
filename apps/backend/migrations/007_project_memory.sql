CREATE TABLE IF NOT EXISTS project_memory (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category varchar(30) NOT NULL,
    subject varchar(160) NOT NULL,
    content text NOT NULL,
    source varchar(30) NOT NULL DEFAULT 'user',
    status varchar(20) NOT NULL DEFAULT 'active',
    confidence integer NOT NULL DEFAULT 100 CHECK (confidence BETWEEN 0 AND 100),
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_project_memory_active ON project_memory (project_id, status, category, subject);
