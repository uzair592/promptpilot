CREATE TABLE IF NOT EXISTS evaluations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    baseline_model_run_id uuid REFERENCES model_runs(id) ON DELETE SET NULL,
    promptpilot_model_run_id uuid REFERENCES model_runs(id) ON DELETE SET NULL,
    method varchar(30) NOT NULL DEFAULT 'heuristic' CHECK (method IN ('heuristic', 'llm_judge')),
    evaluator_provider varchar(80) NOT NULL,
    evaluator_model varchar(160) NOT NULL,
    rubric_version varchar(40) NOT NULL,
    baseline_score double precision CHECK (baseline_score >= 0 AND baseline_score <= 100),
    promptpilot_score double precision CHECK (promptpilot_score >= 0 AND promptpilot_score <= 100),
    overall_delta double precision,
    winner varchar(20) CHECK (winner IN ('baseline', 'promptpilot', 'tie')),
    comparison_summary text,
    baseline_strengths text,
    baseline_weaknesses text,
    promptpilot_strengths text,
    promptpilot_weaknesses text,
    metadata_json text NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluation_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_id uuid NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    response_label varchar(20) NOT NULL CHECK (response_label IN ('single', 'baseline', 'promptpilot')),
    dimension varchar(40) NOT NULL CHECK (
        dimension IN (
            'relevance',
            'completeness',
            'instruction_following',
            'contextual_grounding',
            'clarity'
        )
    ),
    score integer NOT NULL CHECK (score >= 0 AND score <= 100),
    explanation text NOT NULL,
    UNIQUE (evaluation_id, response_label, dimension)
);

CREATE INDEX IF NOT EXISTS ix_evaluations_conversation_created
    ON evaluations (conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_evaluations_project_created
    ON evaluations (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_evaluation_items_evaluation
    ON evaluation_items (evaluation_id);
