CREATE TABLE IF NOT EXISTS benchmark_experiment_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES users(id),
    experiment_scope varchar(80) NOT NULL,
    execution_mode varchar(40) NOT NULL,
    protocol_id varchar(160) NOT NULL,
    protocol_sha256 varchar(64) NOT NULL,
    dataset_sha256 varchar(64) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'staged'
        CHECK (status IN ('staged', 'running', 'completed', 'failed', 'aborted')),
    frozen_role_bindings_json text NOT NULL,
    analysis_call_ceiling integer NOT NULL CHECK (analysis_call_ceiling >= 0),
    question_generation_call_ceiling integer NOT NULL
        CHECK (question_generation_call_ceiling >= 0),
    prompt_generation_call_ceiling integer NOT NULL
        CHECK (prompt_generation_call_ceiling >= 0),
    target_execution_call_ceiling integer NOT NULL
        CHECK (target_execution_call_ceiling >= 0),
    judge_call_ceiling integer NOT NULL CHECK (judge_call_ceiling >= 0),
    total_call_ceiling integer NOT NULL CHECK (total_call_ceiling >= 0),
    reserved_count integer NOT NULL DEFAULT 0 CHECK (reserved_count >= 0),
    succeeded_count integer NOT NULL DEFAULT 0 CHECK (succeeded_count >= 0),
    failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    cancelled_count integer NOT NULL DEFAULT 0 CHECK (cancelled_count >= 0),
    analysis_consumed_count integer NOT NULL DEFAULT 0
        CHECK (analysis_consumed_count >= 0),
    question_generation_consumed_count integer NOT NULL DEFAULT 0
        CHECK (question_generation_consumed_count >= 0),
    prompt_generation_consumed_count integer NOT NULL DEFAULT 0
        CHECK (prompt_generation_consumed_count >= 0),
    target_execution_consumed_count integer NOT NULL DEFAULT 0
        CHECK (target_execution_consumed_count >= 0),
    judge_consumed_count integer NOT NULL DEFAULT 0 CHECK (judge_consumed_count >= 0),
    next_attempt_sequence integer NOT NULL DEFAULT 0 CHECK (next_attempt_sequence >= 0),
    budget_currency varchar(3),
    external_human_approval_verified boolean NOT NULL DEFAULT false
        CHECK (external_human_approval_verified = false),
    abort_reason_code varchar(80),
    failure_reason_code varchar(80),
    repository_commit_sha varchar(64),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    aborted_at timestamptz,
    CONSTRAINT ck_benchmark_experiment_runs_ceiling_total CHECK (
        total_call_ceiling = analysis_call_ceiling
            + question_generation_call_ceiling
            + prompt_generation_call_ceiling
            + target_execution_call_ceiling
            + judge_call_ceiling
    ),
    CONSTRAINT ck_benchmark_experiment_runs_role_budgets CHECK (
        analysis_consumed_count <= analysis_call_ceiling
        AND question_generation_consumed_count <= question_generation_call_ceiling
        AND prompt_generation_consumed_count <= prompt_generation_call_ceiling
        AND target_execution_consumed_count <= target_execution_call_ceiling
        AND judge_consumed_count <= judge_call_ceiling
    ),
    CONSTRAINT ck_benchmark_experiment_runs_total_budget CHECK (
        reserved_count + succeeded_count + failed_count <= total_call_ceiling
    )
);

CREATE INDEX IF NOT EXISTS ix_benchmark_experiment_runs_owner
    ON benchmark_experiment_runs (owner_id);
CREATE INDEX IF NOT EXISTS ix_benchmark_experiment_runs_status
    ON benchmark_experiment_runs (status);
CREATE INDEX IF NOT EXISTS ix_benchmark_experiment_runs_protocol
    ON benchmark_experiment_runs (protocol_sha256);

CREATE TABLE IF NOT EXISTS benchmark_provider_call_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id uuid NOT NULL
        REFERENCES benchmark_experiment_runs(id) ON DELETE CASCADE,
    stable_unit_id varchar(240) NOT NULL,
    fixture_id varchar(160) NOT NULL,
    task_id varchar(160) NOT NULL,
    repetition integer NOT NULL CHECK (repetition >= 1),
    provider_role varchar(40) NOT NULL CHECK (
        provider_role IN (
            'analysis',
            'question_generation',
            'prompt_generation',
            'target_execution',
            'judge'
        )
    ),
    target_condition varchar(20)
        CHECK (target_condition IS NULL OR target_condition IN ('baseline', 'promptpilot')),
    sequence_number integer NOT NULL CHECK (sequence_number >= 1),
    idempotency_key varchar(160) NOT NULL,
    configured_provider varchar(120) NOT NULL,
    configured_model varchar(240) NOT NULL,
    generation_parameter_sha256 varchar(64) NOT NULL,
    request_artifact_sha256 varchar(64) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'reserved'
        CHECK (status IN ('reserved', 'started', 'succeeded', 'failed', 'cancelled')),
    reserved_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
    total_tokens integer CHECK (total_tokens IS NULL OR total_tokens >= 0),
    cost_estimate double precision,
    currency varchar(3),
    safe_error_type varchar(80),
    safe_error_code varchar(80),
    fallback_classification varchar(40),
    observation_outcome varchar(40),
    response_artifact_sha256 varchar(64),
    CONSTRAINT ck_benchmark_attempts_cost_finite CHECK (
        cost_estimate IS NULL OR (
            cost_estimate >= 0
            AND cost_estimate <> 'NaN'::double precision
            AND cost_estimate <> 'Infinity'::double precision
            AND cost_estimate <> '-Infinity'::double precision
        )
    ),
    CONSTRAINT uq_benchmark_attempts_run_idempotency
        UNIQUE (experiment_run_id, idempotency_key),
    CONSTRAINT uq_benchmark_attempts_run_sequence
        UNIQUE (experiment_run_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS ix_benchmark_attempts_run_status
    ON benchmark_provider_call_attempts (experiment_run_id, status);
CREATE INDEX IF NOT EXISTS ix_benchmark_attempts_run_role
    ON benchmark_provider_call_attempts (experiment_run_id, provider_role);
