-- 0124_markx_label_queues.sql (Stealth v10.16 slice P, issue 0182: the Labels queue built in the jobs process)
--
-- The Labels tab's queue (markx/labels.py) is a whole decision reading. It was built inside insight-api on the first
-- open after each decision run (a 2.4 GB peak of Python allocations on a server-sized copy, RSS ~3.4 GB after). Now
-- insight-ingestion's jobs process builds it after each run (markx/jobs.py, the job "labels") and keeps it here; the
-- API only reads what is kept.
--   mx_label_queues       one row a queue: the decision run it reads, the code stamp it was built by (labels.stamp:
--                         the reading's code and the queue's settings), the cut, the offered order, each pool's size
--                         and each (pool, split)'s size, each feature's bar, how long the build took and its peak.
--   mx_label_queue_items  the queue's whole population (queued or not), one row an item, as labels.Item holds it.
-- The headers are kept; a queue's items are kept for the newest labels.KEEP_ITEMS queues (items_kept turns false
-- when they are pruned). The jobs process's job "labels" is a row of mx_jobs. Mark X tables only. Idempotent.

CREATE TABLE IF NOT EXISTS mx_label_queues (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      uuid NOT NULL,
    stamp       text NOT NULL,
    settings    jsonb NOT NULL,
    read_at     timestamptz NOT NULL,          -- the reading's now
    built_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    cut         text,
    queued      uuid[] NOT NULL,               -- the offered items, in order
    pools       jsonb NOT NULL,                -- [[pool, population]] in the queue's order
    sizes       jsonb NOT NULL,                -- [[pool, split, n]]
    bars        jsonb NOT NULL,                -- {feature: its bar (the first item's of the population that has one)}
    items       integer NOT NULL,
    items_kept  boolean NOT NULL DEFAULT true,
    seconds     real,
    peak_mb     real,
    CONSTRAINT mx_label_queues_once UNIQUE (run_id, stamp)
);

CREATE INDEX IF NOT EXISTS mx_label_queues_stamp_idx ON mx_label_queues (stamp, built_at DESC);

CREATE TABLE IF NOT EXISTS mx_label_queue_items (
    queue_id     uuid NOT NULL REFERENCES mx_label_queues (id) ON DELETE CASCADE,
    id           uuid NOT NULL,                 -- the task
    seq          integer NOT NULL,              -- its place in the population (labels.population's order)
    feature      text NOT NULL,
    post         uuid,
    day          timestamptz,
    p            double precision,
    bar          double precision,
    relation     text,
    reason       text,
    accepted     boolean NOT NULL,
    pool         text NOT NULL,
    weight_hint  double precision NOT NULL,
    queued       boolean NOT NULL,
    PRIMARY KEY (queue_id, id)
);

-- The jobs process's job "labels" (markx/jobs.py) builds and keeps the queue; its state is a row of mx_jobs.
ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan', 'labels'));
INSERT INTO mx_jobs (job) VALUES ('labels') ON CONFLICT (job) DO NOTHING;
