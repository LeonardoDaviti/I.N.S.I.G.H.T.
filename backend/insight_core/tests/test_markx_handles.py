"""Issue 0168: a person's handles and reposts credited to their author.

A: the deterministic handle rule over a post's full text (its forms, what it never reads as a handle, platforms apart,
boilerplate lines); B: the role a form gives; C: handles learned from "Name (@handle)" pairs (2+ agreeing posts, the
owner confirms once, a second handle with its time range, never by a name alone); D: an entity named by its handle shown
by the pairs' display name; E: a repost credited to its author in the reading, card, headline and briefing inputs, and
counted as its author's voice when a source follows that author (v10.15, Mark IX's rule; a stranger's stays the feed's).

Invented names and example hosts only. Every database test rolls back (a database whose name ends in _test)."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from insight_core.markx import entity_answers, entity_repair, entity_stage, entity_views, handles as HD
from insight_core.markx import identity as I, schemas, tasks
from insight_core.tests._db import requires_test_db
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_entities import T0, D, H, _Db

LONG = " ".join(f"word{k}" for k in range(12))


def scan(text, *, kind="site", own=None, title="", **kw):
    refs, pairs = HD.scan(kind=kind, own=own, title=title, text=text, **kw)
    return {(r.platform, r.handle): r for r in refs}, pairs


def forms(text, **kw):
    refs, _ = HD.scan(kind=kw.pop("kind", "site"), own=kw.pop("own", None), title=kw.pop("title", ""), text=text, **kw)
    return sorted((r.platform, r.handle, r.form, r.role) for r in refs)


# ---- A, B: the rule (pure) --------------------------------------------------------------------------------------

class Rule(unittest.TestCase):
    def test_each_form_and_its_role(self):
        self.assertEqual(forms("Big news from @ikestrel today"), [("x", "ikestrel", "at", "mention")])
        self.assertEqual(forms("@ikestrel said the launch slips a week"), [("x", "ikestrel", "said", "source")])
        self.assertEqual(forms("- @ikestrel: we ship Nimbus 5 on Monday"), [("x", "ikestrel", "said", "source")])
        self.assertEqual(forms("according to @ikestrel the price drops"), [("x", "ikestrel", "said", "source")])
        self.assertEqual(forms("as https://x.com/ikestrel/status/123456 reports"),
                         [("x", "ikestrel", "status", "source")])
        self.assertEqual(forms("mirror https://nitter.example.net/ikestrel/status/9 and https://xcancel.com/ollo/status/8"),
                         [("x", "ikestrel", "status", "source"), ("x", "ollo", "status", "source")])
        self.assertEqual(forms("follow https://twitter.com/ikestrel"), [("x", "ikestrel", "profile", "mention")])
        self.assertEqual(forms("It ships. — Ivo Kestrel (@ikestrel) May 3, 2026"), [("x", "ikestrel", "embed", "by")])

    def test_a_status_link_names_the_cited_posts_author_not_its_subject(self):
        got = forms("Acme's launch, as https://x.com/ollo/status/77 tells it")
        self.assertEqual(got, [("x", "ollo", "status", "source")], "the tweet's author; Acme is not a handle")

    def test_repost_quote_and_reply_from_the_author_fields(self):
        got = forms("hello", kind="x", own="x:feedowner", title="RT by @feedowner: hello", author="ikestrel",
                    quoted="https://x.com/ollo/status/99")
        self.assertEqual(got, [("x", "ikestrel", "repost", "by"), ("x", "ollo", "quote", "by")],
                         "the repost's author and the quoted tweet's: by; the feed's own account never")
        self.assertEqual(forms("sure", kind="x", own="x:feedowner", title="R to @ikestrel: sure", author="feedowner"),
                         [("x", "ikestrel", "reply", "reply")])
        self.assertEqual(forms("my own words", kind="x", own="x:feedowner", author="feedowner"), [],
                         "a feed's own post cites nobody")

    def test_never_a_handle(self):
        for text in ("write to ivo@kestrel.example", "@media screen { body { color: red } }", "@article{kestrel2026,",
                     "@dataclass\nclass Thing:", "@app.route('/x')", "npm i @types/node", "toot @ivo@social.example",
                     "medium.com/@ikestrel/post", "retina @2x images", "@font-face { }", "ikestrel is a bare word",
                     "x = a@b", "price @ 5pm", "https://www.thejerx.com/blog/2016/3/14/a",
                     "like @auth , @searchable and @function", "the end @a [...]"):
            self.assertEqual(forms(text), [], text)

    def test_telegram_at_is_a_channel_and_platforms_stay_apart(self):
        self.assertEqual(forms("Новости от @kestrelchan", kind="telegram"), [("telegram", "kestrelchan", "at", "mention")])
        self.assertEqual(forms("Новости от @kestrelchan и @ownchan", kind="telegram", own="telegram:ownchan"),
                         [("telegram", "kestrelchan", "at", "mention")], "the channel's own name never")
        got = forms("code https://github.com/ikestrel and https://x.com/ikestrel and https://huggingface.co/ikestrel")
        self.assertEqual(got, [("github", "ikestrel", "profile", "mention"), ("hf", "ikestrel", "profile", "mention"),
                               ("x", "ikestrel", "profile", "mention")], "one handle, three platforms, three accounts")
        self.assertEqual(forms("https://github.com/ikestrel/nimbus https://huggingface.co/models"), [],
                         "a project's page is its maker's (0138), a platform's own page is no account")
        self.assertEqual(forms("by @ivo.bsky.social"), [("bluesky", "ivo.bsky.social", "at", "mention")])

    def test_kept_links_are_read_too(self):
        refs, _ = HD.scan(kind="site", own=None, title="A round-up", text=LONG,
                          links=["https://x.com/ikestrel/status/5", "https://example.com/a"])
        self.assertEqual([(r.handle, r.form, r.line) for r in refs], [("ikestrel", "status", None)])

    def test_the_full_text_is_read(self):
        text = ("filler words here. " * 2000) + "Late in the issue @ikestrel said it ships."
        self.assertGreater(len(text), 30000)
        self.assertEqual(forms(text), [("x", "ikestrel", "said", "source")], "past the guide's 1.5k / 6k characters")

    def test_role_of_a_posts_forms(self):
        self.assertEqual(HD.role_of({"at", "status"}), "source")
        self.assertEqual(HD.role_of({"at", "repost"}), "by")
        self.assertEqual(HD.role_of({"reply", "at"}), "reply", "a reply's @ is the reply")
        self.assertEqual(HD.role_of({"reply", "status"}), "source")
        self.assertEqual(HD.role_of({"profile"}), "mention")

    def test_boilerplate_keys(self):
        one = scan("The weather was odd. Group @ikestrel Discord First item title : text")[0][("x", "ikestrel")]
        two = scan("Other things happened. Group @ikestrel Discord Another item : more")[0][("x", "ikestrel")]
        self.assertEqual(one.line, two.line, "a mention's words around it: a round-up's section header repeats")
        self.assertTrue(one.line.startswith("w:"))
        a = scan("Yesterday @ikestrel said Nimbus 5 ships.")[0][("x", "ikestrel")]
        b = scan("Today @ikestrel said Nimbus 6 ships.")[0][("x", "ikestrel")]
        self.assertNotEqual(a.line, b.line, "a citation's whole sentence")
        self.assertEqual(scan("On 3 May @ikestrel said hi.")[0][("x", "ikestrel")].line,
                         scan("On 4 May @ikestrel said hi.")[0][("x", "ikestrel")].line, "digits aside")


class Pairs(unittest.TestCase):
    def names(self, text, **kw):
        return [(p.platform, p.handle, p.name) for p in scan(text, **kw)[1]]

    def test_display_name_pairs(self):
        self.assertEqual(self.names("Tweet from Ivo Kestrel (@ikestrel) about it"), [("x", "ikestrel", "Ivo Kestrel")])
        self.assertEqual(self.names("which is admitted.” Ivo Kestrel (@IKestrel)"), [("x", "ikestrel", "Ivo Kestrel")])
        self.assertEqual(self.names("the long sentence goes on and on here Ivo Kestrel (@ikestrel)"),
                         [("x", "ikestrel", "Ivo Kestrel")], "a long run keeps its trailing capitalised words")
        self.assertEqual(self.names("ollo (@ollo_dev)"), [("x", "ollo_dev", "ollo")], "a one-word lowercase name")
        self.assertEqual(self.names("Kanal (@kestrelchan)", kind="telegram"), [("telegram", "kestrelchan", "Kanal")])
        self.assertEqual(self.names("see it (@ikestrel)"), [], "no name before it")


class Accounts(unittest.TestCase):
    def test_a_sources_own_account(self):
        self.assertEqual(HD.account_of("rss", "https://nitter.example.net/ikestrel/rss"), ("x", "ikestrel"))
        self.assertEqual(HD.account_of("telegram", "kestrelchan"), ("telegram", "kestrelchan"))
        self.assertEqual(HD.account_of("rss", "https://github.com/ikestrel.atom"), ("github", "ikestrel"))
        self.assertIsNone(HD.account_of("rss", "https://blog.example.com/feed.xml"))


# ---- the database ------------------------------------------------------------------------------------------------

@requires_test_db
class _H(_Db):
    def setUp(self):
        super().setUp()
        self.site = [self.source("rss", f"https://site{n}.example/feed.xml?t={uuid.uuid4().hex}", f"Site {n}")
                     for n in range(4)]

    def source(self, platform, handle, name):
        self.cur.execute("""INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest, settings)
                            VALUES (%s, %s, false, false, %s::jsonb) RETURNING id::text""",
                         (platform, handle, json.dumps({"display_name": name})))
        sid = self.cur.fetchone()[0]
        self.sources.append(sid)
        return len(self.sources) - 1

    def x_feed(self, handle, name):
        return self.source("rss", f"https://nitter.example.net/{handle}/rss?t={uuid.uuid4().hex}", name)

    def say(self, src, at, text, *, title=None, author=None):
        pid = self.post(src, at, title=title or text[:60], text=text)
        if author:
            self.cur.execute("UPDATE posts SET author = %s WHERE id = %s", (author, pid))
        return pid

    def person(self, name="Ivo Kestrel", type_="person", span=None):
        a = self.post(0, T0, title=f"{name} joins Acme")
        b = self.post(1, T0 + H, title=f"{name} talks")
        self.mentions(a, (name, type_, "subject", None, None, span))
        self.mentions(b, (name, type_, "mention", None, None, span))
        self.stage()
        return self.entity_of(a)

    def scan_all(self):
        return HD.scan_pending(self.cur, limit=10000)

    def page(self, eid, **kw):
        return entity_views.entity_page(self.cur, eid, now=T0 + 2 * D, **kw)


class Scanning(_H):
    def test_scan_is_stored_once_and_read_again_when_the_text_changes(self):
        p = self.say(self.site[0], T0, f"{LONG}. Then @ikestrel said it ships.")
        got = self.scan_all()
        self.assertGreaterEqual(got["posts"], 1)
        self.assertTrue(got["done"])
        self.assertEqual(HD.pending(self.cur, 10), [], "nothing left")
        self.cur.execute("UPDATE posts SET content = %s, content_hash = 'h2' WHERE id = %s",
                         (f"{LONG}. Later @ollo said no.", p))
        self.assertEqual(HD.pending(self.cur, 10), [p], "new text: read again")
        self.scan_all()
        cited = HD.posts_citing(self.cur, [{"platform": "x", "handle": "ollo"}])
        self.assertIn(p, cited)
        self.assertNotIn(p, HD.posts_citing(self.cur, [{"platform": "x", "handle": "ikestrel"}]),
                         "the old text's rows stay, unread")
        self.cur.execute("SELECT count(*) FROM mx_handle_refs WHERE post_id = %s", (p,))
        self.assertEqual(self.cur.fetchone()[0], 2, "nothing deleted")

    def test_the_decision_runs_entity_stage_scans(self):
        self.say(self.site[0], T0, f"{LONG}. @ikestrel said so.")
        out = self.stage()
        self.assertGreaterEqual(out["handles"]["scan"]["posts"], 1)
        self.assertIn("learn", out["handles"])


class PersonPage(_H):
    def test_posts_citing_a_confirmed_handle_join_the_page_by_role(self):
        eid = self.person()
        said = self.say(self.site[0], T0 + 2 * H, f"{LONG}. Yesterday @ikestrel said Nimbus 5 ships.")
        status = self.say(self.site[1], T0 + 3 * H, f"{LONG}. The thread: https://x.com/ikestrel/status/42")
        feed = self.x_feed("ollo", "Ollo")
        repost = self.say(feed, T0 + 4 * H, "Nimbus 5 is out", title="RT by @ollo: Nimbus 5 is out", author="ikestrel")
        reply = self.say(feed, T0 + 5 * H, "nice", title="R to @ikestrel: nice", author="ollo")
        mention = self.say(self.site[2], T0 + 6 * H, f"{LONG}. Thanks to @ikestrel for the tip")
        other = self.say(self.site[2], T0 + 7 * H, f"{LONG}. @someoneelse said other things")
        self.scan_all()
        page = self.page(eid)
        ids = {p["id"] for p in page["loose"]}
        self.assertFalse({said, status, repost, mention} & ids, "no handle known yet: nothing joins")
        HD.add_handle(self.cur, self.book(), eid, "x", "@IKestrel")
        page = self.page(eid)
        roles = {p["id"]: p["roles"] for p in page["loose"]}
        self.assertEqual(roles[said], ["source"])
        self.assertEqual(roles[status], ["source"])
        self.assertEqual(roles[repost], ["by"], "their post carried in another feed is theirs")
        self.assertEqual(roles[mention], ["mention"])
        self.assertNotIn(reply, roles, "a reply to them is hidden")
        self.assertNotIn(other, roles)
        self.assertEqual(page["handles"]["replies"], 1)
        self.assertEqual([(h["platform"], h["handle"], h["via"]) for h in page["handles"]["known"]],
                         [("x", "ikestrel", "owner")])
        self.assertIn("@ikestrel", next(p for p in page["loose"] if p["id"] == said)["named"])
        self.assertIn(reply, {p["id"] for p in self.page(eid, replies=True)["loose"]}, "shown when asked")
        HD.add_handle(self.cur, self.book(), eid, "x", "ikestrel", answer="no")
        self.assertNotIn(said, {p["id"] for p in self.page(eid)["loose"]}, "the newest answer counts")

    def test_a_same_handle_on_another_platform_is_another_account(self):
        eid = self.person()
        gh = self.say(self.site[0], T0 + 2 * H, f"{LONG}. Code at https://github.com/ikestrel")
        self.scan_all()
        HD.add_handle(self.cur, self.book(), eid, "x", "ikestrel")
        self.assertNotIn(gh, {p["id"] for p in self.page(eid)["loose"]})

    def test_the_persons_own_source_is_its_handle_and_its_posts_stay_by(self):
        eid = self.person()
        own = self.x_feed("ikestrel", "Ivo Kestrel")
        from insight_core.markx import person_page as PP
        PP.answer_sources(self.cur, self.book(), eid, [self.sources[own]], "yes")
        mine = self.say(own, T0 + 2 * H, "my own words, see https://x.com/ikestrel/status/1", author="ikestrel")
        cites = self.say(self.site[0], T0 + 3 * H, f"{LONG}. @ikestrel said it.")
        self.scan_all()
        page = self.page(eid)
        self.assertEqual([(h["handle"], h["via"]) for h in page["handles"]["known"]], [("ikestrel", "source")],
                         "a followed account of theirs is a known handle, no question")
        roles = {p["id"]: p["roles"] for p in page["loose"]}
        self.assertEqual(roles[mine], ["by"])
        self.assertEqual(roles[cites], ["source"])

    def test_a_line_one_source_repeats_is_boilerplate(self):
        eid = self.person()
        for n in range(HD.BOILER_WINDOW):
            self.say(self.site[3], T0 + n * H, f"Item {n} ends here. Group @ikestrel Discord Topic {uuid.uuid4().hex} : x")
        kept = self.say(self.site[0], T0 + 9 * H, f"{LONG}. Group @ikestrel Discord once")
        self.scan_all()
        HD.add_handle(self.cur, self.book(), eid, "x", "ikestrel")
        loose = {p["id"] for p in self.page(eid)["loose"]}
        self.assertEqual(loose & {kept}, {kept}, "once in another source: a mention")
        self.cur.execute("SELECT id::text FROM posts WHERE source_id = %s", (self.sources[self.site[3]],))
        self.assertFalse({r[0] for r in self.cur.fetchall()} & loose, "the round-up's header in 5 issues: furniture")

    def test_add_handle_refuses_what_is_no_handle(self):
        eid = self.person()
        for platform, handle in (("myspace", "ikestrel"), ("x", "not a handle"), ("x", "far_too_long_for_x_handle")):
            with self.assertRaises(ValueError):
                HD.add_handle(self.cur, self.book(), eid, platform, handle)


@requires_test_db
class Api(unittest.TestCase):
    def test_unknown_entity(self):
        self.assertEqual(call("POST", f"/api/markx/entities/{uuid.uuid4()}/handles",
                              body={"platform": "x", "handle": "ikestrel"})[0], 404)
        self.assertEqual(call("GET", f"/api/markx/entities/{uuid.uuid4()}", query={"replies": "true"})[0], 404)


class Learning(_H):
    def pairs(self, n, text="Tweet from Ivo Kestrel (@ikestrel) about Nimbus", start=0):
        return [self.say(self.site[k % 3], T0 + (start + k) * H, f"{LONG}. {text}") for k in range(n)]

    def item(self, eid, handle="ikestrel"):
        q = entity_views.queue(self.cur)
        got = [x for x in q["open"] if x["kind"] == "handle" and x["a"]["id"] == self.book().root(eid)
               and x["evidence"]["handle"] == handle]
        return got[0] if got else None

    def test_two_agreeing_pairs_propose_a_handle_the_owner_confirms_once(self):
        eid = self.person()
        self.pairs(1)
        self.scan_all()
        HD.learn(self.cur, self.book())
        self.assertIsNone(self.item(eid), "one pair: never")
        self.pairs(1, start=5)
        self.scan_all()
        got = HD.learn(self.cur, self.book())
        self.assertEqual(got["asked"], 1)
        item = self.item(eid)
        self.assertEqual((item["reason"], item["evidence"]["display"], item["evidence"]["pairs"]),
                         ("pairs", "Ivo Kestrel", 2))
        self.assertEqual(HD.learn(self.cur, self.book())["asked"], 0, "asked once")
        entity_answers.answer(self.cur, item["id"], "same")
        page = self.page(eid)
        self.assertEqual([(h["handle"], h["via"], h["display_name"]) for h in page["handles"]["known"]],
                         [("ikestrel", "owner", "Ivo Kestrel")])
        self.assertEqual(HD.learn(self.cur, self.book())["asked"], 0, "an answered handle is never asked again")

    def test_no_and_never_by_the_name_alone(self):
        eid = self.person()
        self.say(self.site[0], T0, f"{LONG}. Ivo Kestrel spoke at the event")
        self.say(self.site[1], T0 + H, f"{LONG}. Ivo Kestrel again, no handle")
        self.scan_all()
        self.assertEqual(HD.learn(self.cur, self.book())["asked"], 0, "a name alone is never a handle")
        self.pairs(2)
        self.scan_all()
        HD.learn(self.cur, self.book())
        entity_answers.answer(self.cur, self.item(eid)["id"], "different")
        self.assertEqual(self.page(eid)["handles"]["known"], [])
        self.assertEqual(HD.learn(self.cur, self.book())["asked"], 0)

    def test_a_glued_word_in_front_still_agrees(self):
        eid = self.person()
        self.pairs(1)
        self.pairs(1, text="the clip. Video Ivo Kestrel (@ikestrel) talks", start=4)
        self.scan_all()
        HD.learn(self.cur, self.book())
        item = self.item(eid)
        self.assertEqual((item["evidence"]["display"], item["evidence"]["pairs"], item["evidence"]["total"]),
                         ("Ivo Kestrel", 2, 2), "“Video Ivo Kestrel” supports “Ivo Kestrel”")

    def test_disagreeing_pairs_ask_nothing(self):
        eid = self.person()
        self.pairs(2)
        self.pairs(2, text="Tweet from Ollo Brand (@ikestrel) about it", start=10)
        self.scan_all()
        HD.learn(self.cur, self.book())
        self.assertIsNone(self.item(eid), "2 of 4 agree: under the bar")

    def test_a_second_handle_paired_with_the_name_is_an_old_account_with_its_range(self):
        eid = self.person()
        HD.add_handle(self.cur, self.book(), eid, "x", "ikestrel")
        self.pairs(2, text="Tweet from Ivo Kestrel (@ivo_old) back then", start=0)
        self.scan_all()
        HD.learn(self.cur, self.book())
        item = self.item(eid, "ivo_old")
        self.assertEqual((item["reason"], item["evidence"]["alias_of"]), ("second_handle", ["ikestrel"]))
        self.assertIsNotNone(item["evidence"]["first"])
        entity_answers.answer(self.cur, item["id"], "same")
        known = {h["handle"]: h for h in self.page(eid)["handles"]["known"]}
        self.assertEqual(set(known), {"ikestrel", "ivo_old"})
        self.assertIsNotNone(known["ivo_old"]["last_seen"], "the old one keeps the months its pairs span")


class NamedByHandle(_H):
    def test_an_entity_named_by_its_handle_shows_the_pairs_name_once_confirmed(self):
        eid = self.person(name="ikestrel", type_="org", span="@ikestrel")
        for k in range(2):
            self.say(self.site[k], T0 + k * H, f"{LONG}. Tweet from Ivo Kestrel (@ikestrel) about it")
        self.scan_all()
        got = HD.learn(self.cur, self.book())
        self.assertEqual(got["asked"], 1)
        q = [x for x in entity_views.queue(self.cur)["open"] if x["kind"] == "handle"]
        self.assertEqual((q[0]["reason"], q[0]["evidence"]["named_by_handle"]), ("named_by_handle", True))
        entity_answers.answer(self.cur, q[0]["id"], "same")
        book = self.book()
        self.assertEqual(book.label(eid), "Ivo Kestrel")
        self.assertIn("ikestrel", [h["handle"] for h in self.page(eid)["handles"]["known"]], "the handle kept")
        entity_repair.shown(self.cur, book, schemas.mention_guides(), roots=[eid])
        self.assertEqual(self.book().label(eid), "Ivo Kestrel", "the run keeps it")

    def test_with_an_entity_of_the_display_name_an_alias_question(self):
        person = self.person()
        a = self.post(2, T0 + 2 * H, title="ikestrel posts")
        self.mentions(a, ("ikestrel", "org", "subject", None, None, "@ikestrel"))
        self.stage()
        named = self.entity_of(a)
        self.assertNotEqual(self.book().root(named), self.book().root(person))
        for k in range(2):
            self.say(self.site[k], T0 + k * H, f"{LONG}. Tweet from Ivo Kestrel (@ikestrel) about it")
        self.scan_all()
        got = HD.learn(self.cur, self.book())
        self.assertEqual(got["aliases"], 1)
        q = [x for x in entity_views.queue(self.cur)["open"] if x["kind"] == "alias" and x["reason"] == "handle_name"]
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["evidence"]["handle"], "ikestrel")
        self.assertEqual(self.book().root(named) != self.book().root(person), True, "never merged by itself")
        entity_answers.answer(self.cur, q[0]["id"], "same")
        book = self.book()
        self.assertEqual(book.root(named), book.root(person))
        self.assertIn("ikestrel", [h["handle"] for h in self.page(person)["handles"]["known"]])


# ---- E: reposts credited to their author -------------------------------------------------------------------------

class Reposts(_H):
    def test_a_repost_says_whose_post_it_is_and_counts_as_its_authors_voice(self):
        feed = self.x_feed("ivokestrel", "Ivo Kestrel")
        other = self.x_feed("ollo", "Ollo")
        repost = self.say(feed, T0, "Acme ships Nimbus 5 today", title="RT by @ivokestrel: Acme ships Nimbus 5 today",
                          author="acmehq")
        again = self.say(other, T0 + H, "Acme ships Nimbus 5 today, again", author="acmehq")
        own = self.say(feed, T0 + 2 * H, "Congrats to the team", author="ivokestrel")
        ps = tasks.load_posts(self.cur, [repost, again, own])
        self.assertEqual((ps[repost].by, ps[again].by, ps[own].by), ("@acmehq", "@acmehq", None))
        text = tasks.read_input(ps[repost])
        self.assertIn("Author: @acmehq (a post by @acmehq shared by Ivo Kestrel; not Ivo Kestrel's own words)", text)
        self.assertNotIn("Author:", tasks.read_input(ps[own]))
        head = tasks.headline_input([ps[repost], ps[own]])
        self.assertIn("[a post by @acmehq shared by Ivo Kestrel, x,", head)
        self.assertIn("[Ivo Kestrel, x,", head)
        self.assertIn("[a post by @acmehq shared by Ivo Kestrel, x,", tasks.card_input([ps[repost]], {}))
        # v10.15: the author is no source here: a stranger's post counts as the feed that carries it (Mark IX's rule)
        self.assertEqual(tasks.voices([ps[repost], ps[again]]), 2, "a stranger reposted by two feeds: the two feeds")
        self.assertEqual(tasks.voices([ps[repost], ps[own]]), 1, "a stranger's post and the feed's own: the feed")
        followed = self.x_feed("acmehq", "Acme")                      # once a source follows the author ...
        ps = tasks.load_posts(self.cur, [repost, again, own])
        self.assertEqual(tasks.voices([ps[repost], ps[again]]), 1, "... one author, two feeds: one voice")
        self.assertEqual(tasks.voices([ps[repost], ps[own]]), 2, "the author's and the feed owner's")
        self.assertEqual(ps[repost].voice, self.sources[followed])
        brief = tasks.briefing_input(T0.date(), [("Acme ships", [ps[repost], ps[own]])])
        self.assertIn("sources: @acmehq, Ivo Kestrel", brief)

    def test_original_author(self):
        self.assertEqual(tasks.original_author("x", "rss", "https://nitter.example.net/feedowner/rss", "Acme", None),
                         "@Acme")
        self.assertIsNone(tasks.original_author("x", "rss", "https://nitter.example.net/feedowner/rss", "FeedOwner", None))
        self.assertIsNone(tasks.original_author("site", "rss", "https://blog.example/feed", "Ivo Kestrel", None),
                          "a blog's author field is its writer, not a repost")
        self.assertEqual(tasks.original_author("telegram", "telegram", "kestrelchan", None, "Acme News"), "Acme News")


if __name__ == "__main__":
    unittest.main()
