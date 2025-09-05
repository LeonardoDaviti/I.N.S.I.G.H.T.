

CREATE TABLE IF NOT EXISTS clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    day DATE NOT NULL,
    method TEXT NOT NULL,
    signature TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    index on day
);

CREATE TABLE IF NOT EXISTS cluster_posts (
    cluster_id UUID NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    PRIMARY KEY (cluster_id, post_id)
);

CREATE INDEX IF NOT EXISTS cluster_posts_post_idx ON cluster_posts(post_id);

CREATE TABLE IF NOT EXISTS meta_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id UUID NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS meta_posts_cluster_idx ON meta_posts(cluster_id);

CREATE TABLE IF NOT EXISTS meta_post_sources (
    meta_post_id UUID NOT NULL REFERENCES meta_posts(id) ON DELETE CASCADE,
    post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    PRIMARY KEY (meta_post_id, post_id)
);

CREATE INDEX IF NOT EXISTS meta_post_sources_post_idx ON meta_post_sources(post_id);