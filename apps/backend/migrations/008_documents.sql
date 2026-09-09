CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name varchar(255) NOT NULL, media_type varchar(120) NOT NULL, source_type varchar(20) NOT NULL DEFAULT 'file',
    source_url text, storage_key varchar(300) NOT NULL UNIQUE, size_bytes integer NOT NULL CHECK (size_bytes >= 0),
    checksum varchar(64) NOT NULL, status varchar(20) NOT NULL DEFAULT 'uploaded', error_message text,
    processing_version varchar(40) NOT NULL DEFAULT 'document-processing-v1', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_documents_project_status ON documents (project_id, status);
CREATE TABLE IF NOT EXISTS document_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL, content text NOT NULL, provenance text, character_count integer NOT NULL,
    processing_version varchar(40) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_document_chunks_document_index ON document_chunks (document_id, chunk_index);
