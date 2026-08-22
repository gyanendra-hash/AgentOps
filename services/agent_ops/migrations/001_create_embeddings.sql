CREATE EXTENSION IF NOT EXISTS vector;

-- 384 dims matches the default local embedding model (bge-small-en-v1.5).
-- Switching EMBEDDING_PROVIDER to "openai" (text-embedding-3-small, 1536
-- dims) requires changing this column's dimension and re-ingesting.
CREATE TABLE IF NOT EXISTS embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings (source);

-- ivfflat needs representative data to cluster well; fine for the runbook's
-- small corpus size today, revisit (or switch to HNSW) once log ingestion
-- makes this table large.
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
    ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
