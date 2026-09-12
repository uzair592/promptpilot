ALTER TABLE model_runs
    ADD COLUMN IF NOT EXISTS generation_parameters_json text NOT NULL DEFAULT '{}';
