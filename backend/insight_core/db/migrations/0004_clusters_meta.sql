

CREATE TABLE IF NOT EXISTS clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    day DATE NOT NULL,
    method TEXT NOT NULL,
    signature TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    index on day
)