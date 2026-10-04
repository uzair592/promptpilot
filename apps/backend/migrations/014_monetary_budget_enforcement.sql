-- Migration 014: Add monetary budget enforcement fields

-- Add monetary budget tracking fields to benchmark_experiment_runs
ALTER TABLE benchmark_experiment_runs
ADD COLUMN IF NOT EXISTS max_spend double precision
    CHECK (max_spend IS NULL OR (max_spend >= 0
        AND max_spend <> 'NaN'::double precision
        AND max_spend <> 'Infinity'::double precision
        AND max_spend <> '-Infinity'::double precision)),
ADD COLUMN IF NOT EXISTS spent_amount double precision NOT NULL DEFAULT 0
    CHECK (spent_amount >= 0
        AND spent_amount <> 'NaN'::double precision
        AND spent_amount <> 'Infinity'::double precision
        AND spent_amount <> '-Infinity'::double precision),
ADD COLUMN IF NOT EXISTS spent_currency varchar(3),
ADD COLUMN IF NOT EXISTS reserved_spend double precision NOT NULL DEFAULT 0
    CHECK (reserved_spend >= 0
        AND reserved_spend <> 'NaN'::double precision
        AND reserved_spend <> 'Infinity'::double precision
        AND reserved_spend <> '-Infinity'::double precision);

-- Add constraint to ensure spent amount doesn't exceed max_spend
-- This will be enforced by the application layer, but we add a DB constraint as well
ALTER TABLE benchmark_experiment_runs
ADD CONSTRAINT IF NOT EXISTS ck_benchmark_experiment_runs_spend_within_limit
    CHECK (max_spend IS NULL OR spent_amount <= max_spend);

-- Add constraint to ensure reserved + spent doesn't exceed max_spend
ALTER TABLE benchmark_experiment_runs
ADD CONSTRAINT IF NOT EXISTS ck_benchmark_experiment_runs_spend_reserved_within_limit
    CHECK (max_spend IS NULL OR (spent_amount + reserved_spend) <= max_spend);

-- Add constraint to ensure spent currency matches budget currency when both are set
ALTER TABLE benchmark_experiment_runs
ADD CONSTRAINT IF NOT EXISTS ck_benchmark_experiment_runs_spend_currency_match
    CHECK (
        spent_currency IS NULL
        OR budget_currency IS NULL
        OR spent_currency = budget_currency
    );

-- Add reserved_spend and spent_currency to provider call attempts for tracking
ALTER TABLE benchmark_provider_call_attempts
ADD COLUMN IF NOT EXISTS cost_estimate_currency varchar(3);

-- The cost_estimate column already exists, we just ensure currency tracking

-- Create index for monetary budget queries
CREATE INDEX IF NOT EXISTS ix_benchmark_experiment_runs_spend
    ON benchmark_experiment_runs (max_spend, spent_amount);