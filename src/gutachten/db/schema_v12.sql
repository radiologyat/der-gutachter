-- v12: resumable pipeline and clearer state.
-- prompt_hash: identical model requests are answered from the stored result, so an
-- interrupted evaluation continues where it stopped instead of starting over.
ALTER TABLE llm_calls ADD COLUMN prompt_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_llm_calls_hash ON llm_calls(case_id, prompt_hash);
-- pipeline_json: what the one-click run was asked to do and how far it got
-- ({"state": "running"|"done"|"error"|"interrupted", "vorentwurf": bool, ...}).
ALTER TABLE cases ADD COLUMN pipeline_json TEXT NOT NULL DEFAULT '{}';
