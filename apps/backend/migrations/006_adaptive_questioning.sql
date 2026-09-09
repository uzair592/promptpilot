ALTER TABLE question_sessions ADD COLUMN IF NOT EXISTS latest_analysis_id uuid REFERENCES prompt_analyses(id) ON DELETE SET NULL;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS source varchar(20) NOT NULL DEFAULT 'fallback';
ALTER TABLE questions ADD COLUMN IF NOT EXISTS options text;
