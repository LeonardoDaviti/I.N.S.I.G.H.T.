CREATE TABLE IF NOT EXISTS topics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  summary TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS topic_posts (
  topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  PRIMARY KEY (topic_id, post_id)
);

CREATE INDEX IF NOT EXISTS topic_posts_post_idx ON topic_posts(post_id);

