
CREATE EXTENSION IF NOT EXISTS vector;
-- Verify installation
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

CREATE TABLE topics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  date DATE NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  embedding vector(1024),                    -- Optional, for future similarity search
  is_outlier BOOLEAN NOT NULL DEFAULT FALSE, -- Flag for outlier topics
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  UNIQUE(date, title)
  
  -- Note: Embeddings are optional. Can be added later for similarity search.
);

-- Recreate topic_posts junction table
CREATE TABLE topic_posts (
  topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now(),
  
  PRIMARY KEY (topic_id, post_id)  -- Composite: post can be in multiple topics
);

-- Topic connections (unchanged)
CREATE TABLE topic_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  target_topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  similarity_score FLOAT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  CHECK (source_topic_id != target_topic_id),
  UNIQUE(source_topic_id, target_topic_id)
);

-- Indexes
CREATE INDEX topics_date_idx ON topics(date);
CREATE INDEX topics_outlier_idx ON topics(is_outlier) WHERE is_outlier = FALSE;
CREATE INDEX topics_embedding_idx ON topics 
  USING ivfflat (embedding vector_cosine_ops) 
  WITH (lists = 100)
  WHERE embedding IS NOT NULL;  -- ✅ Only index non-NULL embeddings

CREATE INDEX topic_posts_topic_idx ON topic_posts(topic_id);
CREATE INDEX topic_posts_post_idx ON topic_posts(post_id);

CREATE INDEX topic_connections_source_idx ON topic_connections(source_topic_id);
CREATE INDEX topic_connections_score_idx ON topic_connections(similarity_score DESC);

-- Grant permissions to application user
GRANT ALL PRIVILEGES ON TABLE topics TO insight;
GRANT ALL PRIVILEGES ON TABLE topic_posts TO insight;
GRANT ALL PRIVILEGES ON TABLE topic_connections TO insight;

-- Grant usage on sequences (for UUID generation)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO insight;
