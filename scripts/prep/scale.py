"""The server-scale copy (prep_scale, scripts/prepared-db.sh build scale): a migrated copy of prep_mxreal inflated
to the server's size, as v10.16 slice M built it by hand (issue 0177; plan/research/load-v1016.md), committed and
deterministic: every id, name, number and vector it writes is a hash of the source rows, so two builds from one
snapshot and one ref make the same synthetic rows (aside from timestamps, and the ids the real story job and decision
runs give what they make).

    python /prep/scale.py [--steps posts,markx,tracks,stories,rounds] [--rounds N]

Run in a backend image with the ref's code at /app and DATABASE_URL the copy (never an original). What it makes:
  posts    every post cloned one and two years back (ids md5(id:yN), titles "[yN] ", addresses "#yN"), their parts
           and links: 49,384 -> 148,152 posts
  markx    the Mark X rows of the 0068 shape emptied, then for 7 posts in 8 (~129.6k): read-v2 and read-v3 readings,
           ent-v4.2 entities answers and their mentions (5-8 a post, ~840k: two of the post's topic's names, the rest
           Zipf over 230k names), bge-m3 vectors (300 topic centroids + noise, 1024-d, HNSW), embed/cite/translate/
           embed_name tasks (real-sized inputs) to ~1.08M tasks and ~0.97M calls (3,000 failed tasks, ~2.6k invalid
           calls, the rest open), ~440k post_post candidates, 1,500 older mx_runs; story window 400 days
  tracks   4 topic tracks (5 sources each, probes with vectors, 100 owner labels, ~56k judged items)
  stories  Mark IX's full story job over every post (the real code)
  rounds   --rounds N (default 0; SCALE_ARGS="--rounds 3" through prepared-db.sh): N decision runs (the real
           decide.run; the first over the whole copy took over 1.5 h and 30 GB), each followed by a fake worker answering
           the questions it planned
           (check/join/pair/merge/connect/card/headline/track/cite, by a hash of the task): entities by identity's own
           linking, Mark X stories, News
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import psycopg

DB = os.environ["DATABASE_URL"]
STEPS = ["posts", "markx", "tracks", "stories", "rounds"]


def say(*a):
    print(f"[scale] {time.strftime('%H:%M:%S')}", *a, file=sys.stderr, flush=True)


def run_sql(conn, label: str, sql: str) -> None:
    t = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    say(f"{label}: {time.monotonic() - t:.1f} s")


def guard(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        name = cur.fetchone()[0]
    conn.commit()   # never left idle in a transaction while the steps run (it held back vacuum for an hour)
    if name in ("insight", "insight_lab") or name.startswith("insight_server_1105"):
        sys.exit(f"refusing to inflate {name}: an original")


# ---- helpers, in the session: h(text) a 32-bit hash, u(text) an id, f(text) a number in [0, 1) ----------------------
HELPERS = """
SET synchronous_commit = off;
SET maintenance_work_mem = '1GB';
CREATE OR REPLACE FUNCTION pg_temp.h(t text) RETURNS bigint LANGUAGE sql IMMUTABLE AS
  $$ SELECT ('x' || substr(md5(t), 1, 8))::bit(32)::bigint $$;
CREATE OR REPLACE FUNCTION pg_temp.u(t text) RETURNS uuid LANGUAGE sql IMMUTABLE AS $$ SELECT md5(t)::uuid $$;
CREATE OR REPLACE FUNCTION pg_temp.f(t text) RETURNS float8 LANGUAGE sql IMMUTABLE AS
  $$ SELECT ('x' || substr(md5(t), 1, 8))::bit(32)::bigint / 4294967296.0 $$;
-- a clone's address: one ending in a number (a tweet's or a Telegram post's id, which the code reads as a number)
-- gets 4 digits more ("000y"), any other "#yN"
CREATE OR REPLACE FUNCTION pg_temp.yurl(u text, y int) RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT CASE WHEN u IS NULL THEN NULL WHEN u ~ '/[0-9]+$' THEN u || lpad(y::text, 4, '0') ELSE u || '#y' || y END $$;
"""

POSTS = """
-- the triggers off for the load (session_replication_role replica: no row trigger, no foreign key check): the search
-- vector is copied with the row instead of computed again, the story queue is not filled (the full story job runs
-- after), the foreign keys hold by construction. With them, 99k posts and 350k links took over 20 min.
SET session_replication_role = replica;
CREATE TEMP TABLE yr AS SELECT y, (y * 365) * interval '1 day' AS back FROM generate_series(1, 2) y;
CREATE TEMP TABLE orig AS SELECT id FROM posts;
-- every column copied as it is (whatever this version's posts hold), the ones a clone must differ in replaced
INSERT INTO posts
SELECT (jsonb_populate_record(NULL::posts, to_jsonb(p) || jsonb_build_object(
          'id', pg_temp.u(p.id || ':y' || y),
          'url', pg_temp.yurl(p.url, y),
          'external_id', p.external_id || ':y' || y,
          'title', CASE WHEN p.title IS NULL THEN NULL ELSE '[y' || y || '] ' || p.title END,
          'content_hash', md5(coalesce(p.content_hash, '') || ':y' || y),
          'normalized_url', pg_temp.yurl(p.normalized_url, y),
          'canonical_url', pg_temp.yurl(p.canonical_url, y),
          'album_of', CASE WHEN p.album_of IS NULL THEN NULL ELSE pg_temp.u(p.album_of || ':y' || y) END,
          'published_at', p.published_at - back, 'fetched_at', p.fetched_at - back, 'surfaced_at', p.surfaced_at - back,
          'created_at', p.created_at - back, 'updated_at', p.updated_at - back,
          'refs_scanned_at', NULL))).*
  FROM posts p JOIN orig USING (id) CROSS JOIN yr
 ORDER BY p.album_of IS NOT NULL, p.id, y;
INSERT INTO post_parts
SELECT (jsonb_populate_record(NULL::post_parts, to_jsonb(pp) || jsonb_build_object(
          'post_id', pg_temp.u(pp.post_id || ':y' || y),
          'title', CASE WHEN pp.title = '' THEN '' ELSE '[y' || y || '] ' || pp.title END,
          'digest', md5(pp.digest || ':y' || y)))).*
  FROM post_parts pp JOIN orig o ON o.id = pp.post_id CROSS JOIN yr;
INSERT INTO post_links
SELECT (jsonb_populate_record(NULL::post_links, to_jsonb(l) || jsonb_build_object(
          'post_id', pg_temp.u(l.post_id || ':y' || y)))).*
  FROM post_links l JOIN orig o ON o.id = l.post_id CROSS JOIN yr;
SET session_replication_role = DEFAULT;
ANALYZE posts; ANALYZE post_parts; ANALYZE post_links;
"""

# The Mark X rows of the snapshot's 0068 shape (ent-v3, read-v2 on a few posts) emptied, as slice M did; the
# per-post rows the backfills keep (handles, round-ups, units) stay and are completed by them.
KEEP_MX = ("mx_guides", "mx_settings", "mx_handle_refs", "mx_handle_pairs", "mx_handle_scans", "mx_roundups", "mx_units",
           "mx_attach", "mx_roundup_issues", "mx_workers", "mx_label_queues", "mx_label_queue_items")

MARKX = """
-- settings: ent-v4.2 entities, the story window 400 days with its backfill done, every post in the reading window
INSERT INTO mx_settings (key, value) VALUES
  ('entities_guide', '"ent-v4.2"'::jsonb), ('story_window_days', '400'::jsonb), ('reading_window_days', 'null'::jsonb),
  ('story_backfill', jsonb_build_object('reached', (SELECT min(COALESCE(surfaced_at, published_at, fetched_at))::date::text FROM posts)))
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- @@ the read posts
-- the posts Mark X has read: 7 in 8; topic t (0..2999) of the names, its vector topic t % 300
CREATE TEMP TABLE rp AS
  SELECT p.id AS post_id, p.fetched_at AS at, pg_temp.h(p.id || ':t') % 3000 AS topic,
         left(coalesce(p.title, '') || E'\\n' || coalesce(p.content, ''), 1100) AS body,
         (ARRAY['report','report','report','commentary','roundup','tool','other'])[1 + pg_temp.h(p.id || ':k') % 7] AS kind
    FROM posts p WHERE pg_temp.h(p.id || ':r') % 8 <> 7;
CREATE UNIQUE INDEX ON rp (post_id);
ANALYZE rp;

-- @@ tasks
-- tasks of one kind for every read post, answered with a call: (kind, guide, input prefix, tokens)
CREATE TEMP TABLE kinds (kind text, guide text, subject text, tin int, tout int);
INSERT INTO kinds VALUES ('read', 'read-v2', 'post', 900, 300), ('read3', 'read-v3', 'post', 950, 320),
  ('entities', 'ent-v4.2', 'post', 1500, 400), ('embed', 'embed-v1', 'post', 400, 0), ('cite', 'cite-v1', 'post', 1100, 120);
INSERT INTO mx_tasks (id, kind, guide, subject_kind, a, input, input_hash, status, attempts, created_at, answered_at)
  SELECT pg_temp.u(rp.post_id || ':' || k.kind), k.kind, k.guide, k.subject, rp.post_id, i.input,
         encode(sha256(convert_to(i.input, 'UTF8')), 'hex'), 'answered', 1, rp.at, rp.at + interval '1 hour'
    FROM rp CROSS JOIN kinds k CROSS JOIN LATERAL (SELECT k.kind || ' ' || rp.post_id || E'\\n' || rp.body AS input) i;

-- @@ answers, calls and readings
-- the answers
CREATE TEMP TABLE ans AS
  SELECT rp.post_id, rp.at, rp.kind, rp.topic,
         jsonb_build_object(
           'kind', rp.kind, 'lang', 'en',
           'events', (ARRAY['one','none','several'])[1 + pg_temp.h(rp.post_id || ':e') % 3],
           'main', jsonb_build_object(
              'headline_en', 'Topic ' || rp.topic || ' ' || (ARRAY['release','study','deal','incident','statement'])[1 + pg_temp.h(rp.post_id || ':a') % 5]
                             || ' ' || left(md5(rp.post_id::text), 10),
              'actors', jsonb_build_array('Topic ' || rp.topic || ' Labs', 'Name ' || (pg_temp.h(rp.post_id || ':o') % 900)),
              'object', 'object ' || left(md5(rp.post_id || 'ob'), 8), 'action', 'released', 'date', NULL,
              'numbers', jsonb_build_array('12 GB', '$40M')),
           'items', CASE WHEN rp.kind = 'roundup' THEN (SELECT jsonb_agg(jsonb_build_object(
                         'headline_en', 'Item ' || i || ' ' || left(md5(rp.post_id || ':' || i), 10),
                         'link', 'https://example.com/' || left(md5(rp.post_id || ':' || i), 12))) FROM generate_series(1, 6) i)
                    ELSE '[]'::jsonb END,
           'mentions', '[]'::jsonb) AS reading
    FROM rp;
INSERT INTO mx_calls (id, task_id, executor, model, valid, tokens_in, tokens_out, ms, cost_usd, created_at, answer)
  SELECT pg_temp.u(a.post_id || ':' || k.kind || ':call'), pg_temp.u(a.post_id || ':' || k.kind), 'claude-code',
         CASE WHEN k.kind = 'embed' THEN 'bge-m3' ELSE 'haiku' END, true, k.tin, k.tout, 1500 + pg_temp.h(a.post_id || k.kind) % 3000,
         CASE WHEN k.kind = 'embed' THEN 0 ELSE 0.001 END, a.at + interval '1 hour',
         CASE k.kind
           WHEN 'read' THEN a.reading
           WHEN 'read3' THEN a.reading || jsonb_build_object(
             'type_why', 'synthetic',
             'event_type', (ARRAY['model_release','product_release','research_result','business_event','policy_legal',
                                  'incident','public_statement','promotion_event','leak_rumour','commentary'])[1 + pg_temp.h(a.post_id || ':et') % 10],
             'origin', (ARRAY['maker','relay','other'])[1 + pg_temp.h(a.post_id || ':og') % 3])
           WHEN 'cite' THEN jsonb_build_object('entities', '[]'::jsonb)
           WHEN 'embed' THEN jsonb_build_object('model', 'bge-m3')
           ELSE jsonb_build_object('entities', '[]'::jsonb) END
    FROM ans a CROSS JOIN kinds k;
INSERT INTO mx_readings (post_id, guide, call_id, kind, events, lang, headline, reading)
  SELECT a.post_id, g.guide, pg_temp.u(a.post_id || ':' || g.kind || ':call'), a.kind, a.reading->>'events', 'en',
         a.reading->'main'->>'headline_en', c.answer
    FROM ans a CROSS JOIN (VALUES ('read', 'read-v2'), ('read3', 'read-v3')) g(kind, guide)
    JOIN mx_calls c ON c.id = pg_temp.u(a.post_id || ':' || g.kind || ':call');

-- @@ mentions
-- ent-v4.2 mentions: 5-8 a post; the first two the topic's names, the rest Zipf over 230k names
CREATE TEMP TABLE mn AS
  SELECT a.post_id, i AS n, CASE WHEN i < 2 THEN 'Topic ' || a.topic || ' ' || (ARRAY['Labs','Model'])[1 + i]
                                  ELSE 'Name ' || floor(exp(pg_temp.f(a.post_id || ':m' || i) * ln(230000)))::int END AS name
    FROM ans a CROSS JOIN LATERAL generate_series(0, 4 + pg_temp.h(a.post_id || ':nm') % 4) i;
INSERT INTO mx_mention_sets (post_id, guide, call_id, at)
  SELECT post_id, 'ent-v4.2', pg_temp.u(post_id || ':entities:call'), at + interval '1 hour' FROM ans;
INSERT INTO mx_mentions (post_id, guide, n, call_id, span, name, name_key, type, role, win)
  SELECT post_id, 'ent-v4.2', n, pg_temp.u(post_id || ':entities:call'), name, name, lower(name),
         (ARRAY['org','person','product','model','place','event'])[1 + pg_temp.h(name) % 6],
         (ARRAY['subject','actor','mentioned','mentioned'])[1 + n % 4], 0
    FROM mn;
UPDATE mx_calls c SET answer = jsonb_build_object('entities', x.ents)
  FROM (SELECT post_id, jsonb_agg(jsonb_build_object('span', name, 'name', name, 'type', 'org', 'role', 'subject') ORDER BY n) ents
          FROM mn GROUP BY post_id) x
 WHERE c.id = pg_temp.u(x.post_id || ':entities:call');
DROP TABLE mn;

-- @@ vectors
-- vectors: 300 topic centroids and two pools of 1,000 noise vectors (1024-d, a hash's sine), each post's vector the
-- normalised sum of its topic's centroid and one of each pool
CREATE TEMP TABLE cen AS SELECT t, (SELECT array_agg(sin(pg_temp.h('c' || t || ':' || d)::float8) ORDER BY d)
                                     FROM generate_series(1, 1024) d)::vector(1024) AS v FROM generate_series(0, 299) t;
CREATE TEMP TABLE nz AS SELECT k, (SELECT array_agg(0.55 * sin(pg_temp.h('n' || k || ':' || d)::float8) ORDER BY d)
                                    FROM generate_series(1, 1024) d)::vector(1024) AS v FROM generate_series(0, 1999) k;
DROP INDEX IF EXISTS mx_embeddings_v_hnsw_idx;
INSERT INTO mx_embeddings (post_id, model, model_sha256, text_hash, v)
  SELECT a.post_id, 'bge-m3', 'synthetic', md5(a.post_id || ':text'),
         l2_normalize(c.v + n1.v + n2.v)::halfvec(1024)
    FROM ans a JOIN cen c ON c.t = a.topic % 300
    JOIN nz n1 ON n1.k = pg_temp.h(a.post_id || ':n1') % 1000
    JOIN nz n2 ON n2.k = 1000 + pg_temp.h(a.post_id || ':n2') % 1000;
-- @@ vectors' index
SET max_parallel_maintenance_workers = 0;   -- a parallel build's shared memory exceeds the container's /dev/shm
CREATE INDEX mx_embeddings_v_hnsw_idx ON mx_embeddings USING hnsw (v halfvec_cosine_ops);
RESET max_parallel_maintenance_workers;

-- @@ candidates
-- post_post candidates: each read post and its next 3-4 posts of the same topic (~440k)
CREATE TEMP TABLE tr AS SELECT post_id, topic, row_number() OVER (PARTITION BY topic % 300 ORDER BY at, post_id) r FROM ans;
INSERT INTO mx_candidates (kind, a, b, source, score, created_at)
  SELECT DISTINCT ON (least(x.post_id, y.post_id), greatest(x.post_id, y.post_id))
         'post_post', least(x.post_id, y.post_id), greatest(x.post_id, y.post_id), 'embedding',
         0.6 + 0.3 * pg_temp.f(x.post_id || ':' || y.post_id), now()
    FROM tr x JOIN tr y ON y.topic % 300 = x.topic % 300 AND y.r BETWEEN x.r + 1 AND x.r + 3 + (pg_temp.h(x.post_id || ':c') % 2)
   ORDER BY least(x.post_id, y.post_id), greatest(x.post_id, y.post_id);
DROP TABLE tr;

-- @@ padding tasks and calls
-- padding: translate (answered), embed_name (answered, the rest open) to ~1.08M tasks and ~0.97M calls
INSERT INTO mx_tasks (id, kind, guide, subject_kind, a, input, input_hash, status, attempts, created_at, answered_at)
  SELECT pg_temp.u(post_id || ':translate'), 'translate', 'translate-v1', 'post', post_id, i.input,
         encode(sha256(convert_to(i.input, 'UTF8')), 'hex'), 'answered', 1, at, at + interval '2 hours'
    FROM ans CROSS JOIN LATERAL (SELECT 'translate ' || post_id || E'\\n' || left(md5(post_id::text) || repeat(' words of the post', 40), 900) AS input) i
   WHERE pg_temp.h(post_id || ':tr') % 2 = 0;
INSERT INTO mx_calls (id, task_id, executor, model, valid, tokens_in, tokens_out, ms, cost_usd, created_at, answer)
  SELECT pg_temp.u(a::text || ':translate:call'), id, 'claude-code', 'haiku', true, 700, 600, 4000, 0.002, answered_at,
         jsonb_build_object('text_en', 'translated ' || left(md5(a::text), 12)) FROM mx_tasks WHERE kind = 'translate';
INSERT INTO mx_tasks (id, kind, guide, subject_kind, a, input, input_hash, status, attempts, created_at, answered_at)
  SELECT pg_temp.u('embed_name:' || i), 'embed_name', 'embed-name-v1', 'entity', pg_temp.u('entity:' || i), x.input,
         encode(sha256(convert_to(x.input, 'UTF8')), 'hex'),
         CASE WHEN i <= 190000 THEN 'answered' ELSE 'open' END, CASE WHEN i <= 190000 THEN 1 ELSE 0 END,
         now() - interval '20 days', CASE WHEN i <= 190000 THEN now() - interval '19 days' END
    FROM generate_series(1, 296000) i CROSS JOIN LATERAL (SELECT 'embed_name Name ' || i || E'\\n' || repeat('context ', 30) AS input) x;
INSERT INTO mx_calls (id, task_id, executor, model, valid, tokens_in, tokens_out, ms, cost_usd, created_at, answer)
  SELECT pg_temp.u(id || ':call'), id, 'claude-code', 'bge-m3', true, 30, 0, 50, 0, answered_at, '{"model": "bge-m3"}'::jsonb
    FROM mx_tasks WHERE kind = 'embed_name' AND status = 'answered';
-- 3,000 failed tasks (reads of posts never read), ~2.6k invalid calls (on answered reads, before their valid one)
INSERT INTO mx_tasks (id, kind, guide, subject_kind, a, input, input_hash, status, attempts, last_error, created_at)
  SELECT pg_temp.u(p.id || ':read:failed'), 'read', 'read-v2', 'post', p.id, x.input, encode(sha256(convert_to(x.input, 'UTF8')), 'hex'),
         'failed', 3, 'invalid answer three times', p.fetched_at
    FROM (SELECT id, fetched_at FROM posts WHERE pg_temp.h(id || ':r') % 8 = 7 ORDER BY md5(id::text) LIMIT 3000) p
    CROSS JOIN LATERAL (SELECT 'read ' || p.id || ' (failed)' AS input) x;
INSERT INTO mx_calls (id, task_id, executor, model, valid, error, tokens_in, tokens_out, ms, cost_usd, created_at, answer)
  SELECT pg_temp.u(t.id || ':invalid'), t.id, 'claude-code', 'haiku', false, 'schema: missing main', 900, 200, 2000, 0.001,
         t.created_at + interval '30 minutes', '{"kind": "report"}'::jsonb
    FROM mx_tasks t WHERE t.kind = 'read' AND t.status = 'answered' AND pg_temp.h(t.id || ':inv') % 50 = 0;

-- @@ older runs
-- 1,500 older decision runs (their counts ~3 kB)
INSERT INTO mx_runs (id, started_at, finished_at, code_version, config, counts)
  SELECT pg_temp.u('run:' || i), now() - (i * interval '30 minutes'), now() - (i * interval '30 minutes') + interval '70 seconds',
         'synthetic', '{}'::jsonb,
         (SELECT jsonb_object_agg('count_' || k, k * i) FROM generate_series(1, 150) k)
    FROM generate_series(1, 1500) i;
ANALYZE;
"""

TRACKS = """
CREATE TEMP TABLE trk AS
  SELECT pg_temp.u('track:' || n) AS id, n, (ARRAY['Local models','Chips and fabs','Space launches','Security incidents'])[n] AS name
    FROM generate_series(1, 4) n;
INSERT INTO folders (id, name, kind, sort_order) SELECT id, name, 'folder', 100 + n FROM trk;
INSERT INTO source_folders (source_id, folder_id)
  SELECT s.source_id, trk.id FROM trk
    JOIN (SELECT source_id, row_number() OVER (ORDER BY count(*) DESC, source_id) r FROM posts GROUP BY 1) s
      ON s.r BETWEEN 10 + (trk.n - 1) * 5 AND 14 + (trk.n - 1) * 5;
INSERT INTO mx_tracks (folder_id, description, excludes, version, version_at, created_at)
  SELECT id, 'Posts about ' || lower(name) || ': releases, measurements, people building with them, what changed and why it matters.',
         'Marketing, giveaways', 1, now() - interval '20 days', now() - interval '20 days' + n * interval '1 minute' FROM trk;
UPDATE mx_tracks t SET v = (SELECT e.v FROM mx_embeddings e JOIN rp ON rp.post_id = e.post_id
                             WHERE rp.topic % 300 = trk.n * 7 ORDER BY e.post_id LIMIT 1),
                       v_hash = encode(sha256(convert_to(regexp_replace(trk.name || ': ' || t.description, '\\s+', ' ', 'g'), 'UTF8')), 'hex')
  FROM trk WHERE trk.id = t.folder_id;
INSERT INTO mx_track_probes (id, track_id, version, near, text, text_hash, v)
  SELECT pg_temp.u('probe:' || trk.n || ':' || k), trk.id, 1, k > 16, 'Probe ' || k || ' of ' || trk.name, md5(trk.name || k),
         (SELECT e.v FROM mx_embeddings e JOIN rp ON rp.post_id = e.post_id
           WHERE rp.topic % 300 = (trk.n * 7 + (k % 3)) % 300 ORDER BY e.post_id OFFSET k LIMIT 1)
    FROM trk, generate_series(1, 20) k;
INSERT INTO mx_labels (id, item_kind, a, b, answer, labeller, created_at)
  SELECT pg_temp.u('label:' || trk.n || ':' || x.post_id), 'track', x.post_id, trk.id, x.ans, 'owner',
         now() - interval '10 days' + x.r * interval '1 minute' FROM trk,
    LATERAL (SELECT post_id, 'in' ans, row_number() OVER (ORDER BY post_id) r FROM (SELECT rp.post_id FROM rp
              WHERE rp.topic % 300 IN (trk.n * 7, trk.n * 7 + 1) ORDER BY rp.post_id LIMIT 60) a
             UNION ALL
             SELECT post_id, 'out', 60 + row_number() OVER (ORDER BY post_id) FROM (SELECT rp.post_id FROM rp
              WHERE rp.topic % 300 = trk.n * 7 + 50 ORDER BY rp.post_id LIMIT 40) b) x;
CREATE TEMP TABLE ti AS
  SELECT trk.id AS track_id, trk.name, trk.n, p.id AS post_id, pg_temp.u('ti:' || trk.n || ':' || p.id) AS task_id,
         pg_temp.u('ti:' || trk.n || ':' || p.id || ':call') AS call_id, pg_temp.h(p.id || ':' || trk.n) % 5 = 0 AS verdict, p.fetched_at
    FROM trk JOIN posts p ON pg_temp.h(p.id || ':track') % 10 IN (trk.n, trk.n + 4) AND pg_temp.h(p.id || ':' || trk.n) % 10 < 4;
INSERT INTO mx_tasks (id, kind, guide, subject_kind, a, b, input, input_hash, status, attempts, priority, created_at, answered_at)
  SELECT task_id, 'track', 'track-v1', 'post_track', post_id, track_id, x.input, encode(sha256(convert_to(x.input, 'UTF8')), 'hex'),
         'answered', 1, 1000, fetched_at, fetched_at + interval '1 hour'
    FROM ti CROSS JOIN LATERAL (SELECT 'track ' || name || ' ' || post_id || repeat(' header words', 90) AS input) x;
INSERT INTO mx_calls (id, task_id, executor, model, valid, created_at, answer)
  SELECT call_id, task_id, 'claude-code', 'haiku', true, fetched_at + interval '1 hour',
         jsonb_build_object('in', verdict, 'confidence', 0.8, 'subtopic', 'sub ' || (pg_temp.h(post_id::text) % 8), 'why', 'because') FROM ti;
INSERT INTO mx_track_items (track_id, post_id, version, task_id, origin, cos, verdict, confidence, subtopic, why, call_id, answered_at, found_by, score)
  SELECT track_id, post_id, 1, task_id, 'passive', 0.5, verdict, 0.8, 'sub ' || (pg_temp.h(post_id::text) % 8), 'because', call_id,
         fetched_at + interval '1 hour', ARRAY['probe'], 0.6 FROM ti;
UPDATE mx_tracks SET history_done_at = now() - interval '5 days', history_at = '1998-01-01', history_id = '00000000-0000-0000-0000-000000000000';
ANALYZE;
"""


def step_posts(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM mx_settings WHERE key = 'prep_scale_posts'")
        if cur.fetchone():
            say("posts: cloned already")
            return
    # the three tables' secondary indexes dropped for the load and made again after it (a bulk build writes far less
    # than 99k rows' index updates, which took 30 min on this disk); the definitions read from the copy itself
    with conn.cursor() as cur:
        cur.execute("""SELECT i.indexrelid::regclass::text, pg_get_indexdef(i.indexrelid) FROM pg_index i
                        WHERE i.indrelid = ANY('{posts,post_parts,post_links}'::regclass[]) AND NOT i.indisunique
                          AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)""")
        indexes = cur.fetchall()
        for name, _ in indexes:
            cur.execute(f"DROP INDEX {name}")
    conn.commit()
    run_sql(conn, f"posts cloned one and two years back ({len(indexes)} indexes set aside)", HELPERS + POSTS)
    t = time.monotonic()
    with conn.cursor() as cur:
        cur.execute("SET maintenance_work_mem = '1GB'")
        for _, ddl in indexes:
            cur.execute(ddl)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO mx_settings (key, value) VALUES ('prep_scale_posts', to_jsonb(now()::text))")
    conn.commit()
    say(f"posts: {len(indexes)} indexes made again in {time.monotonic() - t:.0f} s")


def step_markx(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM mx_settings WHERE key = 'prep_scale_markx'")
        if cur.fetchone():
            say("markx: made already")
            return
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'mx\\_%%' ORDER BY 1")
        empty = [r[0] for r in cur.fetchall() if r[0] not in KEEP_MX]
        cur.execute("TRUNCATE " + ", ".join(empty))
        from insight_core.markx import schemas
        schemas.load_guides(cur)
        if "ent-v4.2" in schemas.ENTITY_ARMS:
            schemas.set_entities_arm(cur, "ent-v4.2")
            schemas.load_guides(cur)
    conn.commit()
    say(f"markx: {len(empty)} Mark X tables emptied, guides loaded")
    run_sql(conn, "helpers", HELPERS)
    for part in MARKX.split("-- @@ "):
        if part.strip():
            label, _, body = part.partition("\n")
            run_sql(conn, "markx: " + (label if body else "settings"), body or label)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO mx_settings (key, value) VALUES ('prep_scale_markx', to_jsonb(now()::text))")
    conn.commit()


def step_tracks(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM mx_tracks")
        if cur.fetchone()[0]:
            say("tracks: made already")
            return
    rp = """CREATE TEMP TABLE IF NOT EXISTS rp AS SELECT post_id, pg_temp.h(post_id || ':t') % 3000 AS topic FROM mx_embeddings;"""
    run_sql(conn, "tracks", HELPERS + rp + TRACKS)


def step_stories(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM mx_settings WHERE key = 'prep_scale_stories'")
        if cur.fetchone():
            say("stories: the full story job ran already")
            return
    conn.commit()
    import main
    t = time.monotonic()
    summary = main.services().stories.recompute(full=True)
    say(f"stories: the full story job in {time.monotonic() - t:.0f} s: "
        + json.dumps({k: v for k, v in summary.items() if not isinstance(v, (dict, list))}, default=str)[:400])
    with conn.cursor() as cur:
        cur.execute("INSERT INTO mx_settings (key, value) VALUES ('prep_scale_stories', to_jsonb(now()::text))")
    conn.commit()


# ---- the fake worker: every open question of these kinds answered by a hash of the task, through tasks.record ------
ANSWERED = ("check", "join", "pair", "merge", "connect", "card", "headline", "track", "cite")


def _h(*xs) -> int:
    return int(hashlib.md5("|".join(map(str, xs)).encode()).hexdigest()[:8], 16)


def fake_answer(t):
    k = t["kind"]
    if k in ("check", "join", "pair", "merge", "connect"):
        rel = ["same_event", "same_event", "same_event", "development", "reaction", "mention", "different", "different",
               "different", "cant_tell"][_h(t["input_hash"]) % 10]
        return {"relation": rel, "confidence": 60 + _h(t["input_hash"], "c") % 40, "reason": "Synthetic answer."}
    if k == "card":
        return {"headline_en": "Story card " + t["input_hash"][:10], "actors": ["Acme"], "object": "thing",
                "action": "did", "date": None, "summary_en": "A summary."}
    if k == "headline":
        return {"headline_en": "Headline " + t["input_hash"][:12], "summary_en": "A summary."}
    if k == "track":
        return {"in": _h(t["input_hash"]) % 5 == 0, "confidence": 0.5 + (_h(t["input_hash"], "c") % 50) / 100,
                "subtopic": "sub " + str(_h(t["a"]) % 8), "why": "Synthetic verdict."}
    if k == "cite":
        return {"entities": []}
    return None


def worker(conn) -> int:
    from psycopg.rows import dict_row
    from insight_core.markx import tasks
    n = 0
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM mx_tasks WHERE kind = ANY(%s) AND status = 'open' ORDER BY created_at, input_hash",
                    (list(ANSWERED),))
        for t in cur.fetchall():
            a = fake_answer(t)
            if a is None:
                continue
            call = hashlib.md5(f"{t['id']}:fake".encode()).hexdigest()
            cur.execute("""INSERT INTO mx_calls (id, task_id, executor, model, valid, tokens_in, tokens_out, ms, cost_usd, answer)
                           VALUES (%s::uuid, %s, 'claude-code', 'haiku', true, 900, 120, 1500, 0.001, %s)""",
                        (call, t["id"], json.dumps(a)))
            cur.execute("UPDATE mx_tasks SET status = 'answered', answered_at = now(), attempts = attempts + 1 WHERE id = %s",
                        (t["id"],))
            tasks.record(cur, t, call, a)
            n += 1
    conn.commit()
    return n


def step_rounds(conn, rounds: int):
    from insight_core.markx import decide
    for r in range(rounds):
        t = time.monotonic()
        with decide.snapshot(DB) as cur:
            out = decide.run(cur)
        run = out.get("run") if isinstance(out.get("run"), dict) else {}
        answered = worker(conn)
        say(f"round {r + 1} of {rounds}: decision run ({run.get('kind')}) and {answered} answers in "
            f"{time.monotonic() - t:.0f} s; stories {out.get('stories')}, tasks added {out.get('tasks_added')}")


def main_() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default=",".join(STEPS))
    # 0 by default: the first decision run over the whole copy (identity's full pass over ~130k read posts) took over
    # 1.5 h and 30 GB of memory on the scratch server (2026-11-13); an agent measuring decision runs makes its own
    ap.add_argument("--rounds", type=int, default=int(os.environ.get("SCALE_ROUNDS", "0")))
    args = ap.parse_args()
    sys.path.insert(0, "/app")
    import logging
    logging.basicConfig(level=logging.WARNING)
    steps = [s for s in args.steps.split(",") if s]
    with psycopg.connect(DB, autocommit=False) as conn:
        guard(conn)
        for s in STEPS:
            if s not in steps:
                continue
            t = time.monotonic()
            if s == "rounds":
                step_rounds(conn, args.rounds)
            else:
                globals()["step_" + s](conn)
            say(f"step {s}: {time.monotonic() - t:.0f} s")
        with conn.cursor() as cur:
            cur.execute("""SELECT json_build_object('posts', (SELECT count(*) FROM posts), 'tasks', (SELECT count(*) FROM mx_tasks),
                             'calls', (SELECT count(*) FROM mx_calls), 'mentions', (SELECT count(*) FROM mx_mentions),
                             'vectors', (SELECT count(*) FROM mx_embeddings), 'entities', (SELECT count(*) FROM mx_entities),
                             'mx_stories', (SELECT count(*) FROM mx_stories), 'news', (SELECT count(*) FROM mx_news),
                             'candidates', (SELECT count(*) FROM mx_candidates), 'track_items', (SELECT count(*) FROM mx_track_items))""")
            print(json.dumps(cur.fetchone()[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main_())
