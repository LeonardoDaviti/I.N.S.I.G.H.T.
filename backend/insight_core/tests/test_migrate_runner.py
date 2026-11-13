import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.migrate import (MIGRATION_LOCK_KEY, acquire_migration_lock, apply_one, hold_migration_lock,
                                     migrate as migrate_all, no_transaction, pending_report, release_migration_lock,
                                     run_one, split_statements, touched_tables)
from insight_core.tests._db import insert_scratch_source, requires_test_db
from insight_core.utils.titles import title_key

MIGRATIONS_DIR = BACKEND_DIR / "insight_core" / "db" / "migrations"


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class MigrationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(DATABASE_URL)
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT 1 FROM schema_migrations LIMIT 1")

        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False)
        self.tmp.write("SELECT 1;")
        self.tmp.flush()
        self.tmp.close()
        self.version = Path(self.tmp.name).name

    def tearDown(self):
        try:
            self.cur.execute("DELETE FROM schema_migrations WHERE version = %s", (self.version,))
            self.conn.commit()
        finally:
            self.conn.close()
            Path(self.tmp.name).unlink(missing_ok=True)

    def test_apply_one_is_idempotent_for_recording(self):
        first = apply_one(self.cur, Path(self.tmp.name), self.version)
        self.assertTrue(first)

        second = apply_one(self.cur, Path(self.tmp.name), self.version)
        self.assertFalse(second)

        self.cur.execute("SELECT count(*) FROM schema_migrations WHERE version = %s", (self.version,))
        self.assertEqual(self.cur.fetchone()[0], 1)


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class FetchScheduleMigrationTests(unittest.TestCase):
    """0019: cadence columns, the source_fetch_state table, the JSONB backfill, the lock."""

    def test_fetch_schedule_schema_exists(self):
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sources' AND column_name = ANY(%s)",
                (["mean_gap_seconds", "cadence_sample_size", "cadence_tier",
                  "cadence_computed_at", "fetch_interval_hours_override"],),
            )
            self.assertEqual(len(cur.fetchall()), 5)
            cur.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'source_fetch_state'"
            )
            self.assertEqual(cur.fetchone()[0], 1)

    def test_migration_lock_is_taken(self):
        holder = psycopg.connect(DATABASE_URL)
        probe = psycopg.connect(DATABASE_URL, autocommit=True)
        try:
            with holder.cursor() as cur:
                acquire_migration_lock(cur)
                self.assertFalse(
                    probe.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                                  (MIGRATION_LOCK_KEY,)).fetchone()[0],
                    "a second migrator must not get the lock while the first transaction is open",
                )
            holder.rollback()
            self.assertTrue(
                probe.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                              (MIGRATION_LOCK_KEY,)).fetchone()[0],
                "the xact lock must end with the transaction",
            )
        finally:
            holder.close()
            probe.close()

    @requires_test_db
    def test_0019_backfill(self):
        """Malformed Mark VIII JSONB must backfill to NULL/0, never abort the migration."""
        sql = (MIGRATIONS_DIR / "0019_fetch_schedule.sql").read_text(encoding="utf-8")
        t0, t1, t2 = "2026-09-01T10:00:00+00:00", "2026-09-02T10:00:00+00:00", "2026-09-03T10:00:00+00:00"
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            healthy = insert_scratch_source(cur, settings_json=json.dumps({
                "display_name": "keep me",
                "ops": {"last_status": "healthy", "last_checked_at": t1, "last_success_at": t1,
                        "last_trigger": "scheduler", "last_fetched_posts": 7},
                "ingest_backoff": {"consecutive_failures": 0, "next_retry_at": None},
            }))
            empty = insert_scratch_source(cur, settings_json=json.dumps({
                "ops": {"last_status": "empty", "last_checked_at": t2, "last_success_at": t0},
            }))
            running = insert_scratch_source(cur, settings_json=json.dumps({
                "ops": {"last_status": "running", "last_checked_at": t1},
            }))
            broken = insert_scratch_source(cur, settings_json=json.dumps({
                "ops": {"last_status": "error", "last_message": "boom", "last_error_at": t2},
                "ingest_backoff": {"consecutive_failures": "x", "next_retry_at": "not-a-date"},
            }))
            ids = [healthy, empty, running, broken]
            cur.execute("DELETE FROM source_fetch_state WHERE source_id = ANY(%s::uuid[])", (ids,))

            cur.execute(sql)

            def snapshot():
                cur.execute(
                    "SELECT source_id::text, last_attempt_at, last_success_at, last_outcome, "
                    "last_trigger, last_fetched_posts, last_error, last_error_at, "
                    "consecutive_failures, next_retry_at "
                    "FROM source_fetch_state WHERE source_id = ANY(%s::uuid[])",
                    (ids,),
                )
                return {r[0]: r[1:] for r in cur.fetchall()}

            rows = snapshot()
            self.assertEqual(set(rows), set(ids))
            ts = lambda v: datetime.fromisoformat(v)  # noqa: E731

            h = rows[healthy]
            self.assertEqual(h[0], ts(t1))
            self.assertEqual(h[1], ts(t1))
            self.assertEqual(h[2], "healthy")
            self.assertEqual(h[3], "scheduler")
            self.assertEqual(h[4], 7)
            self.assertEqual(h[7], 0)

            self.assertEqual(rows[empty][1], ts(t2), "an empty last check is the newer success")
            self.assertEqual(rows[empty][2], "empty")

            self.assertIsNone(rows[running][2], "out-of-set statuses are normalised to NULL")

            b = rows[broken]
            self.assertEqual(b[2], "error")
            self.assertEqual(b[5], "boom")
            self.assertEqual(b[6], ts(t2))
            self.assertEqual(b[7], 1, "an 'error' last status counts as at least one failure, "
                                      "even when the failure count is malformed")
            self.assertIsNone(b[8], "a malformed retry time backfills to NULL")

            cur.execute("SELECT settings FROM sources WHERE id = ANY(%s::uuid[])", (ids,))
            for (settings,) in cur.fetchall():
                self.assertNotIn("ops", settings)
                self.assertNotIn("ingest_backoff", settings)
            cur.execute("SELECT settings->>'display_name' FROM sources WHERE id = %s", (healthy,))
            self.assertEqual(cur.fetchone()[0], "keep me", "other settings keys survive")

            cur.execute(sql)
            self.assertEqual(snapshot(), rows, "0019 must be idempotent")
        finally:
            conn.rollback()
            conn.close()

    @requires_test_db
    def test_0022_repairs_error_rows_backfilled_with_no_failures(self):
        """Databases that ran the old 0019 have last_outcome='error' with 0 failures: count 1."""
        sql = (MIGRATIONS_DIR / "0022_fetch_state_error_failures.sql").read_text(encoding="utf-8")
        t1, t2 = datetime.fromisoformat("2026-09-02T10:00:00+00:00"), datetime.fromisoformat("2026-09-03T10:00:00+00:00")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            ids = {name: insert_scratch_source(cur) for name in
                   ("stale_error", "never_succeeded", "recovered", "counted", "healthy")}
            cur.execute("DELETE FROM source_fetch_state WHERE source_id = ANY(%s::uuid[])", (list(ids.values()),))
            rows = {
                "stale_error": ("error", t1, t2, 0, None),        # failed after its last success
                "never_succeeded": ("error", None, t2, 0, None),
                "recovered": ("error", t2, t1, 0, None),          # a success since the error
                "counted": ("error", t1, t2, 3, t2),              # already counted: untouched
                "healthy": ("healthy", t2, t1, 0, None),
            }
            for name, (outcome, success, error, failures, retry) in rows.items():
                cur.execute(
                    "INSERT INTO source_fetch_state (source_id, last_outcome, last_success_at, last_error_at, "
                    "consecutive_failures, next_retry_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (ids[name], outcome, success, error, failures, retry),
                )

            cur.execute(sql)
            cur.execute(sql)  # idempotent

            cur.execute("SELECT source_id::text, consecutive_failures, next_retry_at FROM source_fetch_state "
                        "WHERE source_id = ANY(%s::uuid[])", (list(ids.values()),))
            got = {sid: (n, retry) for sid, n, retry in cur.fetchall()}
            self.assertEqual(got[ids["stale_error"]], (1, None), "retry stays NULL: the next tick retries")
            self.assertEqual(got[ids["never_succeeded"]], (1, None))
            self.assertEqual(got[ids["recovered"]], (0, None))
            self.assertEqual(got[ids["counted"]], (3, t2))
            self.assertEqual(got[ids["healthy"]], (0, None))
        finally:
            conn.rollback()
            conn.close()


ARXIV_RSS = [
    "https://rss.arxiv.org/rss/cs.AI",
    "https://rss.arxiv.org/rss/cs.CL",
    "https://rss.arxiv.org/rss/cs.LG",
    "https://rss.arxiv.org/rss/physics.optics",
]


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class ReaderMigrationTests(unittest.TestCase):
    """0020 (read-state projection) and 0021 (arXiv out of the main digest)."""

    def test_reader_state_schema_exists(self):
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'post_reader_state'")
            self.assertEqual(cur.fetchone()[0], 1)
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)",
                (["posts_feed_order_idx", "posts_source_feed_order_idx", "post_reader_state_starred_idx"],),
            )
            self.assertEqual(len(cur.fetchall()), 3)

    @requires_test_db
    def test_0020_backfill_from_interactions(self):
        sql = (MIGRATIONS_DIR / "0020_reader_state.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            source = insert_scratch_source(cur)
            posts = []
            for n in range(3):
                cur.execute(
                    "INSERT INTO posts (source_id, url) VALUES (%s, %s) RETURNING id",
                    (source, f"https://test.invalid/mark-ix/post/{n}/{source}"),
                )
                posts.append(str(cur.fetchone()[0]))
            opened, starred, unstarred = posts
            t = lambda h: f"2026-10-0{h}T10:00:00+00:00"  # noqa: E731
            for post_id, kind, ts in [
                (opened, "opened", t(2)), (opened, "opened", t(1)), (opened, "reading_session", t(3)),
                (starred, "unfavorited", t(1)), (starred, "favorited", t(2)),
                (unstarred, "favorited", t(1)), (unstarred, "unfavorited", t(2)),
            ]:
                cur.execute(
                    "INSERT INTO post_interactions (post_id, interaction_type, created_at) VALUES (%s, %s, %s)",
                    (post_id, kind, ts),
                )
            cur.execute(sql)
            cur.execute(
                "SELECT post_id::text, read_at, starred_at FROM post_reader_state WHERE post_id = ANY(%s::uuid[])",
                (posts,),
            )
            rows = {r[0]: r[1:] for r in cur.fetchall()}
            self.assertEqual(rows[opened], (datetime.fromisoformat(t(1)), None), "read_at = first open")
            self.assertEqual(rows[starred], (None, datetime.fromisoformat(t(2))), "latest toggle was a favorite")
            self.assertEqual(rows[unstarred], (None, None), "latest toggle was an unfavorite")
            cur.execute(sql)  # idempotent
        finally:
            conn.rollback()
            conn.close()

    @requires_test_db
    def test_0021_arxiv_main_digest(self):
        sql = (MIGRATIONS_DIR / "0021_arxiv_out_of_main_digest.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            for url in ARXIV_RSS:
                cur.execute(
                    """
                    INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest)
                    VALUES ('rss', %s, true, true)
                    ON CONFLICT (platform, handle_or_url) DO UPDATE SET enabled = true, in_main_digest = true
                    """,
                    (url,),
                )
            other = insert_scratch_source(cur, enabled=True, in_main_digest=True)

            cur.execute(sql)

            cur.execute(
                "SELECT handle_or_url, enabled, in_main_digest FROM sources WHERE handle_or_url = ANY(%s)",
                (ARXIV_RSS,),
            )
            rows = cur.fetchall()
            self.assertEqual(len(rows), 4)
            for url, enabled, in_main_digest in rows:
                self.assertTrue(enabled, url)
                self.assertFalse(in_main_digest, url)
            cur.execute("SELECT enabled, in_main_digest FROM sources WHERE id = %s", (other,))
            self.assertEqual(cur.fetchone(), (True, True), "other sources are untouched")
        finally:
            conn.rollback()
            conn.close()


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class MediaUrlEntitiesMigrationTests(unittest.TestCase):
    """0023 decodes the HTML entities older ingests left in posts.media_urls."""

    @requires_test_db
    def test_0023_unescapes_media_urls(self):
        sql = (MIGRATIONS_DIR / "0023_media_url_entities.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            source = insert_scratch_source(cur)
            cases = {
                "amp": ["https://preview.redd.it/a.jpg?w=1&amp;s=x", "https://x.invalid/b.png"],
                "numeric": ["https://i0.wp.com/a.jpg?a=1&#038;b=2&#38;c=3"],
                "double": ["https://x.invalid/a.jpg?a=1&amp;#038;b=2"],
                "clean": ["https://x.invalid/a.jpg?a=1&b=2"],
                "mixed": ["https://x.invalid/a.jpg?a=1&amp;b=2", 7],
                "empty": [],
            }
            ids = {}
            for name, urls in cases.items():
                cur.execute("INSERT INTO posts (source_id, url, title, content, media_urls) "
                            "VALUES (%s, %s, 't', 'c', %s::jsonb) RETURNING id",
                            (source, f"https://test.invalid/mark-ix/0023/{name}", json.dumps(urls)))
                ids[name] = cur.fetchone()[0]

            cur.execute(sql)
            cur.execute(sql)  # idempotent

            cur.execute("SELECT id, media_urls FROM posts WHERE id = ANY(%s)", (list(ids.values()),))
            got = dict(cur.fetchall())
            self.assertEqual(got[ids["amp"]], ["https://preview.redd.it/a.jpg?w=1&s=x", "https://x.invalid/b.png"],
                             "order kept")
            self.assertEqual(got[ids["numeric"]], ["https://i0.wp.com/a.jpg?a=1&b=2&c=3"])
            self.assertEqual(got[ids["double"]], ["https://x.invalid/a.jpg?a=1&b=2"])
            self.assertEqual(got[ids["clean"]], cases["clean"])
            self.assertEqual(got[ids["mixed"]], ["https://x.invalid/a.jpg?a=1&b=2", 7], "non-strings survive as-is")
            self.assertEqual(got[ids["empty"]], [])
        finally:
            conn.rollback()
            conn.close()



@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class StalePostLimitMigrationTests(unittest.TestCase):
    """0029 drops the stored max_posts_per_fetch nothing shows or edits any more (issue 0029)."""

    @requires_test_db
    def test_0029_drops_stored_post_limits(self):
        sql = (MIGRATIONS_DIR / "0029_drop_stored_post_limits.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            stale = insert_scratch_source(cur, settings_json=json.dumps(
                {"max_posts_per_fetch": 3, "display_name": "Kept", "page_watch": {"prefix": "/news/"}}))
            plain = insert_scratch_source(cur, settings_json=json.dumps({"priority": 5}))
            cur.execute(sql)
            cur.execute(sql)  # idempotent
            cur.execute("SELECT id::text, settings FROM sources WHERE id = ANY(%s::uuid[])", ([stale, plain],))
            got = dict(cur.fetchall())
            self.assertEqual(got[stale], {"display_name": "Kept", "page_watch": {"prefix": "/news/"}})
            self.assertEqual(got[plain], {"priority": 5})
        finally:
            conn.rollback()
            conn.close()

@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class GwernNoiseMigrationTests(unittest.TestCase):
    """0036 deletes the Gwern posts stored from /doc/ and /newsletter/ before 0043 (issue 0048)."""

    @requires_test_db
    def test_0036_deletes_gwern_directories_and_newsletters(self):
        sql = (MIGRATIONS_DIR / "0036_gwern_noise_cleanup.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()

            def source(platform, handle):
                cur.execute(
                    """
                    INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest)
                    VALUES (%s, %s, false, false)
                    ON CONFLICT (platform, handle_or_url) DO UPDATE SET enabled = false
                    RETURNING id
                    """,
                    (platform, handle),
                )
                return cur.fetchone()[0]

            gwern = source("rss", "https://www.gwern.net/")
            substack = source("rss", "https://gwern.substack.com/feed")
            saved = source("saved", "Saved")
            other = insert_scratch_source(cur)
            tag = os.urandom(4).hex()
            posts = {}
            for name, source_id, url in [
                ("directory", gwern, f"https://gwern.net/doc/ai/{tag}/index"),
                ("abstract", gwern, f"https://gwern.net/doc/ai/{tag}/abstract"),
                ("copy", gwern, f"https://www.gwern.net/doc/{tag}/1990-smith.html"),
                ("newsletter", gwern, f"https://gwern.net/newsletter/2020/{tag}"),
                ("essay", gwern, f"https://gwern.net/spaced-repetition-{tag}"),
                ("blog", gwern, f"https://gwern.net/blog/2026/{tag}"),
                ("doc_word", gwern, f"https://gwern.net/doctor-{tag}"),
                ("kept", gwern, f"https://gwern.net/doc/kept/{tag}/index"),
                ("later", gwern, f"https://gwern.net/newsletter/later/{tag}"),
                ("noted", gwern, f"https://gwern.net/doc/noted/{tag}/index"),
                ("saved", saved, f"https://gwern.net/doc/saved/{tag}/index"),
                ("substack", substack, f"https://gwern.substack.com/doc/{tag}"),
                ("other_site", other, f"https://example.invalid/doc/{tag}"),
            ]:
                cur.execute("INSERT INTO posts (source_id, url, title, content) VALUES (%s, %s, 't', 'c') "
                            "RETURNING id", (source_id, url))
                posts[name] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO post_reader_state (post_id, read_at, resume_block, resume_blocks) "
                "VALUES (%s, now(), 3, 10)", (posts["directory"],))
            cur.execute("INSERT INTO post_reader_state (post_id, read_at, starred_at) VALUES (%s, now(), now())",
                        (posts["kept"],))
            cur.execute("INSERT INTO post_reader_state (post_id, later_at) VALUES (%s, now())", (posts["later"],))
            cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened')",
                        (posts["newsletter"],))
            cur.execute("INSERT INTO post_notes (post_id, notes_markdown) VALUES (%s, 'n')", (posts["noted"],))

            cur.execute(sql)

            cur.execute("SELECT id FROM posts WHERE id = ANY(%s)", (list(posts.values()),))
            left = {r[0] for r in cur.fetchall()}
            gone = {name for name, post_id in posts.items() if post_id not in left}
            self.assertEqual(gone, {"directory", "abstract", "copy", "newsletter"})
            for table in ("post_reader_state", "post_interactions", "post_notes"):
                cur.execute(f"SELECT count(*) FROM {table} t WHERE NOT EXISTS "
                            "(SELECT 1 FROM posts p WHERE p.id = t.post_id)")
                self.assertEqual(cur.fetchone()[0], 0, f"{table} has no orphans")
            cur.execute("SELECT count(*) FROM post_reader_state WHERE post_id = ANY(%s)",
                        ([posts["kept"], posts["later"]],))
            self.assertEqual(cur.fetchone()[0], 2, "Keep and Later stay with their posts")
            cur.execute("SELECT notes_markdown FROM post_notes WHERE post_id = %s", (posts["noted"],))
            self.assertEqual(cur.fetchone(), ("n",), "a note keeps its post")

            cur.execute(sql)  # a second run deletes nothing
            self.assertEqual(cur.rowcount, 0)
        finally:
            conn.rollback()
            conn.close()


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class OnePostOneAddressMigrationTests(unittest.TestCase):
    """0038 merges the posts stored twice under one normalized_url and title (issue 0049)."""

    @requires_test_db
    def test_0038_merges_copies_and_keeps_the_owners_state(self):
        sql = (MIGRATIONS_DIR / "0038_one_post_one_address.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            source = insert_scratch_source(cur)
            tag = os.urandom(4).hex()
            base = f"https://simon.test/{tag}"
            posts = {}
            for name, url, normalized, days_ago, *title in [
                ("only_new_old", f"{base}/a/#atom-everything", f"{base}/a", 2),
                ("only_new_new", f"{base}/a/", f"{base}/a", 1),
                ("both_old", f"{base}/b/#atom-everything", f"{base}/b", 2),
                ("both_new", f"{base}/b/", f"{base}/b", 1),
                ("none_old", f"{base}/c/#atom-everything", f"{base}/c", 2),
                ("none_new", f"{base}/c/?utm_source=rss", f"{base}/c", 1),
                # Stored by the old normalizer: http kept, an address fragment dropped.
                ("http_old", f"http://www.simon.test/{tag}/d", f"http://simon.test/{tag}/d", 2),
                ("http_new", f"{base}/d", f"{base}/d", 1),
                ("spa_1", f"{base}/#!/post/1", f"{base}/", 2),
                ("spa_2", f"{base}/#!/post/2", f"{base}/", 1),
                # The same title under post_title_key: merged.
                ("ent_old", f"http://{tag}.test/atomic/", f"http://{tag}.test/atomic", 2, "Atomic design in&nbsp;1998"),
                ("ent_new", f"https://{tag}.test/atomic/", f"https://{tag}.test/atomic", 1, " Atomic  Design in 1998"),
                # Daring Fireball's shapes on the server: one address, other posts, other titles.
                ("df_post", f"{base}/dma", f"{base}/dma", 2, "★ What Is the Point of the DMA?"),
                ("df_fn", f"{base}/dma#fn1-2026-08-24", f"{base}/dma", 1, "Footnote Regarding the GDPR"),
                ("df_iphone", f"{base}/iphones", f"{base}/iphones", 2, "★ The iPhones 18 Pro"),
                ("df_text", f"{base}/iphones#:~:text=OR%20IS%20IT", f"{base}/iphones", 1, "One More Thing"),
                ("df_q2", f"{base}/auth-md?utm_campaign=q22026", f"{base}/auth-md", 3, "Auth.md"),
                ("df_q3", f"{base}/auth-md?utm_campaign=q32026", f"{base}/auth-md", 2, "WorkOS: Agents"),
                ("df_q4", f"{base}/auth-md?utm_campaign=q42026", f"{base}/auth-md", 1, "[Sponsor] WorkOS"),
            ]:
                cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, fetched_at) "
                            "VALUES (%s, %s, %s, %s, 'c', now() - make_interval(days => %s)) RETURNING id",
                            (source, url, normalized, (title or ["t"])[0], days_ago))
                posts[name] = cur.fetchone()[0]
            cur.execute("INSERT INTO post_reader_state (post_id, read_at) VALUES (%s, now())",
                        (posts["only_new_new"],))
            cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened')",
                        (posts["only_new_new"],))
            cur.execute("INSERT INTO post_watch (post_id, source_id, text_hash, next_check_at) "
                        "VALUES (%s, %s, 'h', now())", (posts["only_new_old"], source))
            cur.execute("INSERT INTO post_reader_state (post_id, read_at, resume_block, resume_blocks) "
                        "VALUES (%s, now(), 3, 10)", (posts["both_old"],))
            cur.execute("INSERT INTO post_reader_state (post_id, later_at, resume_block, resume_blocks) "
                        "VALUES (%s, now(), 7, 10)", (posts["both_new"],))
            cur.execute("INSERT INTO post_notes (post_id, notes_markdown) VALUES (%s, 'my note')",
                        (posts["both_new"],))

            cur.execute(sql)

            cur.execute("SELECT id FROM posts WHERE id = ANY(%s)", (list(posts.values()),))
            left = {r[0] for r in cur.fetchall()}
            kept = {name for name, post_id in posts.items() if post_id in left}
            self.assertEqual(kept, {"only_new_new", "both_old", "none_old", "http_old", "spa_1", "spa_2", "ent_old",
                                    "df_post", "df_fn", "df_iphone", "df_text", "df_q2", "df_q3", "df_q4"})
            cur.execute("SELECT url FROM posts WHERE id = %s", (posts["both_old"],))
            self.assertEqual(cur.fetchone(), (f"{base}/b/#atom-everything",), "the kept row keeps its url")
            cur.execute("SELECT normalized_url FROM posts WHERE id = ANY(%s) ORDER BY url",
                        ([posts["spa_1"], posts["spa_2"]],))
            self.assertEqual([r[0] for r in cur.fetchall()], [f"{base}/#!/post/1", f"{base}/#!/post/2"])

            cur.execute("SELECT read_at IS NOT NULL FROM post_reader_state WHERE post_id = %s",
                        (posts["only_new_new"],))
            self.assertEqual(cur.fetchone(), (True,))
            cur.execute("SELECT count(*) FROM post_interactions WHERE post_id = %s", (posts["only_new_new"],))
            self.assertEqual(cur.fetchone(), (1,))
            cur.execute("SELECT text_hash FROM post_watch WHERE post_id = %s", (posts["only_new_new"],))
            self.assertEqual(cur.fetchone(), ("h",), "the page watch moves to the kept row")
            cur.execute("SELECT read_at IS NOT NULL, later_at IS NOT NULL, resume_block, resume_blocks "
                        "FROM post_reader_state WHERE post_id = %s", (posts["both_old"],))
            self.assertEqual(cur.fetchone(), (True, True, 7, 10), "read, Later and the furthest position")
            cur.execute("SELECT notes_markdown FROM post_notes WHERE post_id = %s", (posts["both_old"],))
            self.assertEqual(cur.fetchone(), ("my note",))

            # Every table pointing at posts is one the migration merges; a new one needs a look.
            # 0039's and 0040's tables (issues 0050, 0051) come after 0038 and are derived: the
            # story job rebuilds them.
            cur.execute("SELECT conrelid::regclass::text FROM pg_constraint "
                        "WHERE contype = 'f' AND confrelid = 'posts'::regclass")
            # posts.album_of (0051, issue 0069) is derived too: the saver folds a channel's albums again.
            derived = {"post_links", "stories", "story_posts", "story_mentions", "news_stories", "news_posts", "classics",
                       "posts", "post_edges", "story_keys", "post_parts",
                       "post_refs",   # 0076 (issue 0125): read again from the post's text by the saver and the backfill
                       "series_posts"}   # 0083 (issue 0134): made again by the story job's series pass
            self.assertEqual({r[0] for r in cur.fetchall()} - derived,
                             {"post_reader_state", "post_notes", "post_interactions", "post_watch"})
            for table in ("post_reader_state", "post_interactions", "post_notes", "post_watch"):
                cur.execute(f"SELECT count(*) FROM {table} t WHERE NOT EXISTS "
                            "(SELECT 1 FROM posts p WHERE p.id = t.post_id)")
                self.assertEqual(cur.fetchone()[0], 0, f"{table} has no orphans")

            def snapshot():
                cur.execute("SELECT p.id, p.normalized_url, r.read_at, r.later_at, r.resume_block, "
                            "n.notes_markdown FROM posts p "
                            "LEFT JOIN post_reader_state r ON r.post_id = p.id "
                            "LEFT JOIN post_notes n ON n.post_id = p.id WHERE p.source_id = %s ORDER BY p.id",
                            (source,))
                return cur.fetchall()

            before = snapshot()
            cur.execute(sql)  # a second run changes nothing
            self.assertEqual(snapshot(), before)
        finally:
            conn.rollback()
            conn.close()

    @requires_test_db
    def test_0041_drops_the_unique_index_the_first_0038_made(self):
        sql = (MIGRATIONS_DIR / "0041_same_post_same_title.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()

            def indexes():
                cur.execute("SELECT indexname, indexdef LIKE 'CREATE UNIQUE%%' FROM pg_indexes "
                            "WHERE tablename = 'posts' AND indexdef LIKE '%%(normalized_url)'")
                return sorted(cur.fetchall())

            self.assertEqual(indexes(), [("posts_normalized_url_idx", False)])
            # A database that ran the first 0038 (insight_preview, insight_lab): no function, and
            # the unique index in place of the plain one.
            cur.execute("DROP INDEX posts_normalized_url_idx")
            cur.execute("DROP FUNCTION post_title_key(text)")
            cur.execute("CREATE UNIQUE INDEX posts_normalized_url_unique ON posts (normalized_url)")
            cur.execute(sql)
            self.assertEqual(indexes(), [("posts_normalized_url_idx", False)])
            cur.execute("SELECT post_title_key('A&amp;B')")
            self.assertEqual(cur.fetchone(), ("a&b",))
            cur.execute(sql)  # a second run changes nothing
            self.assertEqual(indexes(), [("posts_normalized_url_idx", False)])
        finally:
            conn.rollback()
            conn.close()

    def test_0038_and_0041_define_one_title_rule(self):
        def definition(name):
            text = (MIGRATIONS_DIR / name).read_text(encoding="utf-8")
            start = text.index("CREATE OR REPLACE FUNCTION post_title_key")
            return text[start:text.index("$fn$;", start)]

        self.assertEqual(definition("0038_one_post_one_address.sql"), definition("0041_same_post_same_title.sql"))

    @requires_test_db
    def test_post_title_key(self):
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            for title, key in [
                (None, ""), ("", ""), ("  Two   words\n", "two words"),
                ("Atomic design in&nbsp;1998", "atomic design in 1998"),
                ("Atomic Design in\u00a01998", "atomic design in 1998"),
                ("Tom &amp; Jerry", "tom & jerry"), ("Tom &#38; Jerry", "tom & jerry"),
                ("&lt;b&gt; &quot;q&quot; &apos;a&apos; &#39;b&#x27;", "<b> \"q\" 'a' 'b'"),
                ("It&#8217;s &rsquo;", "it's '"), ("&amp;lt;", "&lt;"), ("&#38;#65;", "&#65;"),
                ("&#0; &#xD800; ok", "ok"), ("★ The iPhones 18 Pro", "★ the iphones 18 pro"),
                ("Introducing 𝙻𝙵𝙼𝟹 “today”", 'introducing lfm3 "today"'),   # issue 0071: as utils/titles.py
            ]:
                cur.execute("SELECT post_title_key(%s)", (title,))
                self.assertEqual(cur.fetchone()[0], key, title)
                if not title or "&#0;" not in title:
                    self.assertEqual(title_key(title), key, f"the Python rule, {title!r}")
        finally:
            conn.rollback()
            conn.close()



class MigrationFileTests(unittest.TestCase):
    """v10.17 (0188): the runner's reading of a file, no database."""

    def test_split_statements_keeps_quotes_comments_and_dollar_bodies(self):
        sql = """-- no transaction
-- a header; with a semicolon
CREATE TABLE IF NOT EXISTS t (a text DEFAULT 'x;y');
/* a block; comment */
CREATE OR REPLACE FUNCTION f() RETURNS int AS $$ BEGIN RETURN 1; END $$ LANGUAGE plpgsql;
DO $body$ BEGIN PERFORM 1; END $body$;
CREATE INDEX CONCURRENTLY IF NOT EXISTS t_a ON t (a)
"""
        parts = split_statements(sql)
        self.assertEqual(len(parts), 4, parts)
        self.assertIn("'x;y'", parts[0])
        self.assertTrue(parts[1].startswith("/* a block; comment */"))
        self.assertIn("RETURN 1; END $$", parts[1])
        self.assertIn("PERFORM 1; END $body$", parts[2])
        self.assertTrue(parts[3].startswith("CREATE INDEX CONCURRENTLY"))
        self.assertEqual(split_statements("-- only a comment\n;\n"), [])

    def test_no_transaction_marker_is_read_from_the_header_only(self):
        self.assertTrue(no_transaction("-- 0200_big_index.sql\n-- no transaction\nCREATE INDEX CONCURRENTLY x ON t (a);"))
        self.assertFalse(no_transaction("-- 0200.sql\nSELECT 1;"))
        self.assertFalse(no_transaction("\n" * 10 + "-- no transaction\nSELECT 1;"))

    def test_touched_tables(self):
        sql = """-- UPDATE commented_out SET a = 1;
CREATE TABLE IF NOT EXISTS mx_new (id int);
ALTER TABLE ONLY public.posts ADD COLUMN IF NOT EXISTS x int;
CREATE UNIQUE INDEX IF NOT EXISTS posts_x ON posts (x);
CREATE INDEX CONCURRENTLY ON ONLY "sources" (id);
UPDATE sources SET x = 1 WHERE false;
INSERT INTO schema_migrations (version) VALUES ('v');
DELETE FROM mx_old WHERE false;
CREATE TRIGGER t_x AFTER INSERT OR UPDATE ON mx_new FOR EACH ROW EXECUTE FUNCTION f();
"""
        self.assertEqual(touched_tables(sql), ["mx_new", "public.posts", "posts", "sources", "schema_migrations",
                                               "mx_old"])


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class PerMigrationTransactionTests(unittest.TestCase):
    """v10.17 (0188): a transaction per migration, a lock timeout with retries, `-- no transaction` files, the
    runner's session lock and --pending's tables. Scratch tables named for this process, dropped after."""

    def setUp(self):
        self.tag = f"zz_mig_{os.getpid()}"
        self.dir = Path(tempfile.mkdtemp())
        self.conn = psycopg.connect(DATABASE_URL, autocommit=True)
        self.versions = []

    def tearDown(self):
        try:
            self.conn.execute(f"DROP TABLE IF EXISTS {self.tag}, {self.tag}_b CASCADE")
            self.conn.execute("DELETE FROM schema_migrations WHERE version = ANY(%s)", (self.versions,))
        finally:
            self.conn.close()
            for p in self.dir.iterdir():
                p.unlink()
            self.dir.rmdir()

    def file(self, name: str, sql: str) -> Path:
        version = f"9990_{self.tag}_{name}.sql"
        self.versions.append(version)
        path = self.dir / version
        path.write_text(sql, encoding="utf-8")
        return path

    def recorded(self, path: Path) -> bool:
        return self.conn.execute("SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = %s)",
                                 (path.name,)).fetchone()[0]

    def test_a_failed_migration_keeps_the_ones_before_it(self):
        ok = self.file("a", f"CREATE TABLE {self.tag} (a int);")
        bad = self.file("b", f"CREATE TABLE {self.tag}_b (a int); SELECT 1 / 0;")
        with self.assertRaises(psycopg.errors.DivisionByZero):
            migrate_all(self.conn, self.dir)
        self.assertTrue(self.recorded(ok), "the first migration is committed on its own")
        self.assertFalse(self.recorded(bad))
        self.assertIsNone(self.conn.execute("SELECT to_regclass(%s)", (f"{self.tag}_b",)).fetchone()[0],
                          "the failed migration's own statements rolled back")
        probe = psycopg.connect(DATABASE_URL, autocommit=True)
        try:
            self.assertTrue(probe.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,)).fetchone()[0],
                            "the runner's lock is released after a failure")
            probe.execute("SELECT pg_advisory_unlock(hashtext(%s))", (MIGRATION_LOCK_KEY,))
        finally:
            probe.close()

    def test_a_held_lock_is_waited_for_with_retries(self):
        self.conn.execute(f"CREATE TABLE {self.tag} (a int)")
        path = self.file("alter", f"ALTER TABLE {self.tag} ADD COLUMN IF NOT EXISTS b int;")
        holder = psycopg.connect(DATABASE_URL)
        holder.execute(f"LOCK TABLE {self.tag} IN ACCESS EXCLUSIVE MODE")
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                holder.rollback()          # the long query ends while the migration waits
        try:
            self.assertTrue(run_one(self.conn, path, path.name, lock_timeout=0.2, retries=3, wait=0.5, sleep=sleep))
        finally:
            holder.close()
        self.assertEqual(waits, [0.5, 1.0])
        self.assertTrue(self.recorded(path))

    def test_a_lock_never_freed_fails_after_the_retries(self):
        self.conn.execute(f"CREATE TABLE {self.tag} (a int)")
        path = self.file("alter", f"ALTER TABLE {self.tag} ADD COLUMN b int;")
        holder = psycopg.connect(DATABASE_URL)
        holder.execute(f"LOCK TABLE {self.tag} IN ACCESS EXCLUSIVE MODE")
        waits = []
        try:
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                run_one(self.conn, path, path.name, lock_timeout=0.1, retries=1, wait=0.0, sleep=waits.append)
        finally:
            holder.close()
        self.assertEqual(len(waits), 1)
        self.assertFalse(self.recorded(path))
        self.assertEqual(self.conn.execute("SHOW lock_timeout").fetchone()[0], "0",
                         "the lock timeout is the migration's own (SET LOCAL)")

    def test_no_transaction_file_builds_an_index_concurrently(self):
        path = self.file("index", f"""-- {self.tag}: a big index
-- no transaction
CREATE TABLE IF NOT EXISTS {self.tag} (a int);
DROP INDEX CONCURRENTLY IF EXISTS {self.tag}_a;
CREATE INDEX CONCURRENTLY IF NOT EXISTS {self.tag}_a ON {self.tag} (a);
""")
        self.assertTrue(run_one(self.conn, path, path.name))
        self.assertTrue(self.recorded(path))
        self.assertIsNotNone(self.conn.execute("SELECT to_regclass(%s)", (f"{self.tag}_a",)).fetchone()[0])
        self.assertEqual(self.conn.execute("SHOW lock_timeout").fetchone()[0], "0")

    def test_the_runner_lock_outlives_a_commit(self):
        probe = psycopg.connect(DATABASE_URL, autocommit=True)
        try:
            hold_migration_lock(self.conn)
            with self.conn.transaction():
                self.conn.execute("SELECT 1")
            self.assertFalse(probe.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                                           (MIGRATION_LOCK_KEY,)).fetchone()[0],
                             "a second runner (or a restore) waits while the first runs, across its commits")
            release_migration_lock(self.conn)
            self.assertTrue(probe.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                                          (MIGRATION_LOCK_KEY,)).fetchone()[0])
        finally:
            probe.close()

    def test_pending_lists_the_tables_and_their_rows(self):
        self.file("touch", f"-- {self.tag}: touch\nUPDATE sources SET name = name WHERE false;\n"
                           f"CREATE TABLE {self.tag} (a int);\n")
        with self.conn.cursor() as cur:
            lines = pending_report(cur, self.dir)
        self.assertEqual(lines[0], f"  {self.tag}: touch")
        self.assertRegex(lines[1], rf"touches: sources \((~[\d,]+ rows|rows unknown)\), {self.tag} \(new\)")
        self.assertEqual(lines[-1], "1 migration(s) will run at the start")


if __name__ == "__main__":
    unittest.main()
