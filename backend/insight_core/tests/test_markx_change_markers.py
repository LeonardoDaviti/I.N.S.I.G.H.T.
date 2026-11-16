"""v10.22 (issue 0216, migration 0147): the change markers the planners and the passes read instead of scanning.

  - a post's text stamp (plan_marks.STAMP): its row's version and mx_post_stamps' n. Each write of what tasks.load_posts
    reads moves it (the post's row, its parts, its kept links, its source's shown name, the `linked` original its page
    is), only for that post (a source's rename: its posts only); a write of something else moves nothing;
  - mx_tasks' stamp (unchanged.table_stamps): its change log, by kind. An insert, update, delete of a kind moves that
    kind's stamp and no other's; a TRUNCATE moves every kind's; the log's prune never leaves a stamp where it was.

Invented names and example hosts only. Every test rolls back (a database whose name ends in _test)."""
from __future__ import annotations

import unittest

from insight_core.markx import plan_marks, tasks, unchanged
from insight_core.tests._db import requires_test_db
from insight_core.tests.test_markx_story_window import Window as _Window


class Window(unittest.TestCase):   # the story window tests' database and posts, not their tests
    setUp, post = _Window.setUp, _Window.post


@requires_test_db
class APostsStamp(Window):
    def stamp(self, pid):
        self.cur.execute(f"SELECT {plan_marks.STAMP} FROM posts p WHERE p.id = %s", (pid,))
        return self.cur.fetchone()[0]

    def two(self):
        a, b = self.post(self.now, "Acme released Widget 4"), self.post(self.now, "Globex opened a lab")
        return a, b, self.stamp(a), self.stamp(b)

    def moved(self, a, b, sa, sb, what):
        self.assertNotEqual(self.stamp(a), sa, what + " moves the post's stamp")
        self.assertEqual(self.stamp(b), sb, what + " moves no other post's stamp")

    def test_its_parts_move_it(self):
        a, b, sa, sb = self.two()
        self.cur.execute("UPDATE post_parts SET title = title WHERE post_id = %s", (a,))
        self.moved(a, b, sa, sb, "its parts written again")
        sa = self.stamp(a)
        self.cur.execute("DELETE FROM post_parts WHERE post_id = %s", (a,))
        self.moved(a, b, sa, sb, "its parts deleted")

    def test_its_links_move_it(self):
        a, b, sa, sb = self.two()
        self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) "
                         "VALUES (%s, 'https://example.com/a', 'example.com', 0)", (a,))
        self.moved(a, b, sa, sb, "a link added")
        sa = self.stamp(a)
        self.cur.execute("UPDATE post_links SET link_text = 'Example' WHERE post_id = %s", (a,))
        self.moved(a, b, sa, sb, "a link's words")
        sa = self.stamp(a)
        self.cur.execute("DELETE FROM post_links WHERE post_id = %s", (a,))
        self.moved(a, b, sa, sb, "a link removed")

    def test_a_new_post_has_one_and_its_row_moves_it(self):
        a, b, sa, sb = self.two()
        self.assertTrue(sa.isdigit() and sb.isdigit() and sa != sb, "each post saved has its own version")
        self.cur.execute("UPDATE posts SET title = 'Acme released Widget 5' WHERE id = %s", (a,))
        self.moved(a, b, sa, sb, "its row written")

    def test_its_sources_shown_name_moves_it_and_another_field_does_not(self):
        a, b, sa, sb = self.two()
        self.cur.execute("SELECT source_id FROM posts WHERE id = %s", (a,))
        source = self.cur.fetchone()[0]
        self.cur.execute("UPDATE sources SET enabled = NOT enabled WHERE id = %s", (source,))
        self.assertEqual((self.stamp(a), self.stamp(b)), (sa, sb), "a field no render reads moves nothing")
        self.cur.execute("UPDATE sources SET settings = settings || '{\"display_name\": \"Renamed\"}' WHERE id = %s",
                         (source,))
        self.moved(a, b, sa, sb, "its source renamed")

    def test_the_linked_original_of_its_page_moves_it(self):
        a, b, sa, sb = self.two()
        page = "https://example.com/the-page"
        self.cur.execute("UPDATE post_parts SET link_target = %s, link_kind = 'page' WHERE post_id = %s", (page, a))
        sa = self.stamp(a)
        self.cur.execute("INSERT INTO story_originals (kind, url, outcome) VALUES ('collect', %s, 'found')", (page,))
        self.assertEqual((self.stamp(a), self.stamp(b)), (sa, sb), "another kind of original moves nothing")
        self.cur.execute("INSERT INTO story_originals (kind, url, outcome, post_id) VALUES ('linked', %s, 'found', %s)",
                         (page, b))
        self.moved(a, b, sa, sb, "its page stored")
        sa = self.stamp(a)
        self.cur.execute("DELETE FROM story_originals WHERE kind = 'linked' AND url = %s", (page,))
        self.moved(a, b, sa, sb, "its page's original gone")

    def test_a_deleted_post_leaves_no_marker(self):
        a, b, sa, sb = self.two()
        self.cur.execute("UPDATE post_parts SET title = title WHERE post_id = %s", (a,))
        self.cur.execute("DELETE FROM posts WHERE id = %s", (a,))
        self.cur.execute("SELECT count(*) FROM mx_post_stamps WHERE post_id = %s", (a,))
        self.assertEqual(self.cur.fetchone()[0], 0)


@requires_test_db
class ATasksStamp(Window):
    def stamps(self):
        return (unchanged.table_stamps(self.cur, ["mx_tasks[read]"])["mx_tasks[read]"],
                unchanged.table_stamps(self.cur, ["mx_tasks[entities]"])["mx_tasks[entities]"])

    def test_each_kind_moves_its_own_stamp(self):
        pid = self.post(self.now, "Acme released Widget 4")
        read, ents = self.stamps()
        tid, _ = tasks.read_task(self.cur, pid)
        r2, e2 = self.stamps()
        self.assertNotEqual(r2, read, "an insert of read")
        self.assertEqual(e2, ents, "no other kind's")
        self.cur.execute("UPDATE mx_tasks SET priority = priority + 1 WHERE id = %s", (tid,))
        r3, e3 = self.stamps()
        self.assertNotEqual(r3, r2, "an update")
        self.assertEqual(e3, ents)
        self.cur.execute("DELETE FROM mx_tasks WHERE id = %s", (tid,))
        r4, e4 = self.stamps()
        self.assertNotEqual(r4, r3, "a delete")
        self.assertEqual(e4, ents)
        self.cur.execute("UPDATE mx_tasks SET priority = priority WHERE false")
        self.assertEqual(self.stamps(), (r4, e4), "a statement that wrote no row moves nothing")

    def test_a_truncate_moves_every_kind(self):
        before = self.stamps()
        self.cur.execute("TRUNCATE mx_tasks CASCADE")
        after = self.stamps()
        self.assertNotEqual(after[0], before[0])
        self.assertNotEqual(after[1], before[1])

    def test_the_prune_never_leaves_a_stamp_where_it_was(self):
        pid = self.post(self.now, "Acme released Widget 4")
        tasks.read_task(self.cur, pid)
        self.cur.execute("UPDATE mx_table_changes SET at = now() - interval '2 days'")
        before = self.stamps()
        unchanged._prune(self.cur)
        self.cur.execute("SELECT count(*) FROM mx_table_changes WHERE at < now() - interval '1 hour'")
        self.assertEqual(self.cur.fetchone()[0], 0, "the old rows are gone")
        self.assertNotEqual(self.stamps()[0], before[0], "a pass after the prune runs once more")
        kept = self.stamps()
        unchanged._prune(self.cur)
        self.assertEqual(self.stamps(), kept, "nothing old left: the prune deletes nothing")
