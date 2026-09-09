-- PromptPilot project ownership and membership slice. PostgreSQL 15+.
CREATE TABLE IF NOT EXISTS projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES users(id),
    name varchar(160) NOT NULL,
    description text,
    domain varchar(80),
    status varchar(20) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_projects_status CHECK (status IN ('active', 'archived'))
);

CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id);
CREATE INDEX IF NOT EXISTS ix_projects_status ON projects (status);

CREATE TABLE IF NOT EXISTS project_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role varchar(20) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_members_project_user UNIQUE (project_id, user_id),
    CONSTRAINT ck_project_members_role CHECK (role IN ('owner', 'editor', 'member')),
    CONSTRAINT ck_project_members_status CHECK (status IN ('active', 'removed'))
);

CREATE INDEX IF NOT EXISTS ix_project_members_project_id ON project_members (project_id);
CREATE INDEX IF NOT EXISTS ix_project_members_user_id ON project_members (user_id);
CREATE INDEX IF NOT EXISTS ix_project_members_status ON project_members (status);
