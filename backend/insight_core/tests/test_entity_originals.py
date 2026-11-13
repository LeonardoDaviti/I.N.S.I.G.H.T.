"""Issue 0138: originals from entities. The pure rules (A's addresses and their order, B's trigger, C's match, D2's
threshold), A on the database (the entity stage writes mx_entity_addresses; merges read the target's; a front page is
never one), the entity page's Original and, when no current reading names the entity, the posts an earlier guide
named it in; B and C through OriginalsService (Collect originals' credit and record; the lookup's switch off by
default), D1's Pages rows and D2's kept suppliers.

No network: FakeHttp answers every request. Invented names and example hosts only. The A and page tests roll back;
the service tests commit (a database whose name ends in _test) and clean their rows."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import decide, entity_addresses as EA, entity_stage, entity_views, identity as I
from insight_core.markx import names as N, repo, schemas, tasks
from insight_core.tests._db import clear_tables, db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_markx_api import MX_TABLES
from insight_core.tests.test_markx_entities import D, H, T0, _Db
from insight_core.tests.test_story_originals import OriginalsCase, run
from insight_core.utils import entity_originals as E
from insight_core.utils import originals_rules as O
from insight_core.utils.url_normalization import normalize_url

PAPER = "https://arxiv.org/abs/2611.01234"
CODE = "https://github.com/nimbus-lab/nimbus-proof"
DEMO = "https://huggingface.co/spaces/nimbus-lab/nimbus_demo"
TITLE = "Proving the Nimbus Hypothesis with Lattices"
DELETE_ORDER = ("mx_entity_handles", "mx_handle_refs", "mx_handle_pairs", "mx_handle_scans", "mx_back", "mx_mention_sets", "mx_perspectives", "mx_sheets", "mx_labels", "mx_briefings", "mx_news",
                "mx_connections", "mx_story_posts", "mx_entity_surges", "mx_entity_vectors", "mx_entity_pins",
                "mx_entity_queue", "mx_entity_redirects", "mx_entity_aliases", "mx_entity_addresses", "mx_mentions",
                "mx_entity_fixes", "mx_entities", "mx_stories", "mx_candidate_posts", "mx_candidates", "mx_jobs", "mx_runs", "mx_embeddings",
                "mx_readings", "mx_calls", "mx_tasks", "mx_workers")


def m(name, type_="document", role="subject", **kw):
    return dict({"span": name, "name": name, "name_key": tasks.name_key(name), "type": type_, "role": role,
                 "maker": None, "family": None, "version": None, "variant": None, "size": None, "build": None,
                 "by_name": None, "ref": None, "rule": None}, **kw)


class Rules(unittest.TestCase):
    def test_address_kinds(self):
        self.assertEqual([E.address_kind(u) for u in (PAPER, PAPER.replace("abs", "pdf") + "v2", CODE, DEMO,
                                                       "https://nimbus.example/blog/nimbus-4")],
                         ["paper", "paper", "code", "demo", "release"])
        self.assertEqual(E.paper_ref("https://arxiv.org/pdf/2611.01234v3"), "arXiv:2611.01234")
        self.assertEqual(E.paper_ref("https://doi.org/10.1145/12345.678"), "doi:10.1145/12345.678")

    def test_rule_1_the_identifier_then_the_one_paper_of_the_only_document(self):
        links = [PAPER.replace("abs", "pdf"), PAPER, CODE]
        self.assertEqual(E.by_identifier(ref="arXiv:2611.01234", span_ids=[], links=links, documents=3, is_document=True),
                         PAPER, "the mention's id: the post's own page link, not its file")
        self.assertEqual(E.by_identifier(ref=None, span_ids=[], links=links, documents=1, is_document=True), PAPER)
        self.assertIsNone(E.by_identifier(ref=None, span_ids=[], links=links, documents=2, is_document=True),
                          "two documents in the post: which paper is whose is not known")
        self.assertIsNone(E.by_identifier(ref=None, span_ids=[], links=links + ["https://arxiv.org/abs/2611.09999"],
                                          documents=1, is_document=True), "two papers linked")
        self.assertIsNone(E.by_identifier(ref=None, span_ids=[], links=links, documents=1, is_document=False))
        self.assertEqual(E.by_identifier(ref=None, span_ids=["arXiv:2611.05555"], links=[], documents=0, is_document=True),
                         normalize_url("https://arxiv.org/abs/2611.05555"), "no link: the canonical page")

    def test_rule_2_a_title_names_it_by_the_name_key(self):
        names = {N.key(TITLE)}
        self.assertTrue(E.by_title(f"[2611.01234] {TITLE}", names, N.key))
        self.assertTrue(E.by_title(f"{TITLE} | A Summary Site", names, N.key))
        self.assertTrue(E.by_title(TITLE.upper().replace(" ", "  "), names, N.key))
        self.assertFalse(E.by_title(f"Notes on {TITLE}", names, N.key), "a title about it is not its page")
        self.assertFalse(E.by_title("Ok", {"ok"}, N.key), "a name too short names nothing")

    def test_rule_3_a_page_on_the_makers_own_site(self):
        ok = dict(makers={"acme labs"}, names={"nimbus 4"}, squash=N.squash)
        self.assertTrue(E.by_maker("https://acmelabs.example/news/introducing-nimbus-4", "Introducing Nimbus 4", **ok))
        self.assertFalse(E.by_maker("https://acmelabs.example/", "Introducing Nimbus 4", **ok), "never a front page")
        self.assertFalse(E.by_maker("https://other.example/news/nimbus-4", "Introducing Nimbus 4", **ok), "another site")
        self.assertFalse(E.by_maker("https://acmelabs.example/news/x", "Introducing Nimbus 40", **ok), "word for word")
        self.assertFalse(E.by_maker("https://acmelabs.example/research/x", "How Nimbus 4 helped a lab ship a new product",
                                    **ok), "named in passing: the name is under half the title's words")

    def test_pages_no_thing_is_released_at(self):
        for url in ("https://workspace.example/marketplace/app/nimbus/1", "https://apps.example/us/app/nimbus/id1",
                    "https://raw.example/acme/nimbus/main/docs/providers.md", "https://acme.example/docs/nimbus",
                    "https://help.acme.example/nimbus"):
            self.assertTrue(E.not_a_release(url), url)
        for url in ("https://acme.example/index/introducing-nimbus-4", "https://acme.example/news/nimbus.html",
                    "https://pkgs.example/project/nimbus"):
            self.assertFalse(E.not_a_release(url), url)

    def test_what_a_long_read_cites(self):
        own = "https://essays.example/articles/1"
        self.assertTrue(E.cited_page("https://news.example/a-one-segment-slug", own), "a news site's /<slug>")
        self.assertTrue(E.cited_page("https://arxiv.org/abs/2611.01234", own))
        self.assertFalse(E.cited_page("https://essays.example/articles/2", own), "its own site")
        self.assertFalse(E.cited_page("https://product.example/", own), "a front page")
        self.assertFalse(E.cited_page("https://x.com/someone", own), "a platform's profile")
        self.assertFalse(E.cited_page("https://docs.example/guide", own), "a reference page")

    def test_the_order_of_the_rules_and_the_original(self):
        t = datetime(2026, 11, 1, tzinfo=timezone.utc)
        picked = E.pick([("paper", "https://a.example/paper/1", E.TITLE, t), ("paper", PAPER, E.IDENTIFIER, t + H),
                         ("release", "https://b.example/r", E.MAKER, t), ("release", "https://c.example/r", E.TITLE, t + H)])
        self.assertEqual(picked["paper"][0], PAPER, "an identifier before a title, whenever found")
        self.assertEqual(picked["release"][0], "https://c.example/r", "a title before the maker's page")
        self.assertEqual(E.original_of(picked), ("paper", PAPER))
        self.assertEqual(E.original_of({"release": ("https://c.example/r", E.TITLE, t), "code": (CODE, E.TITLE, t)}),
                         ("release", "https://c.example/r"))
        self.assertIsNone(E.original_of({"code": (CODE, E.IDENTIFIER, t)}), "a repository alone is no original")

    def test_the_trigger(self):
        self.assertTrue(E.triggered(2, False))
        self.assertTrue(E.triggered(1, True), "one voice's News lead")
        self.assertFalse(E.triggered(1, False))
        self.assertFalse(E.triggered(0, True))

    def test_the_lookup_matches_by_the_title_key_and_an_author(self):
        results = [("Something else", ["R. Varga"], "https://arxiv.org/abs/2611.00001"),
                   (TITLE + ".", ["Rena Varga", "Ivo Kestrel"], PAPER)]
        self.assertEqual(E.lookup_match(TITLE, ["Ivo Kestrel"], results, N.key), PAPER)
        self.assertEqual(E.lookup_match(TITLE, ["I. Kestrel"], results, N.key), PAPER, "a surname")
        self.assertIsNone(E.lookup_match(TITLE, ["Someone Other"], results, N.key), "no author of `by`")
        self.assertIsNone(E.lookup_match(TITLE, [], results, N.key), "no `by`: no match")
        self.assertEqual(E.by_names("Rena Varga, Ivo Kestrel and Lu Wen"), ["Rena Varga", "Ivo Kestrel", "Lu Wen"])

    def test_the_lookup_answers_are_parsed(self):
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2611.01234v1</id>'
                f'<title>{TITLE}</title><author><name>Ivo Kestrel</name></author></entry></feed>')
        self.assertEqual(E.parse_arxiv(atom), [(TITLE, ["Ivo Kestrel"], PAPER)])
        self.assertEqual(E.parse_arxiv("not xml"), [])
        crossref = {"message": {"items": [{"title": [TITLE], "DOI": "10.1145/ABC", "author": [{"given": "Ivo", "family": "Kestrel"}]}]}}
        self.assertEqual(E.parse_crossref(crossref), [(TITLE, ["Ivo Kestrel"], normalize_url("https://doi.org/10.1145/abc"))])
        self.assertIn("export.arxiv.org/api/query?search_query=ti%3A", E.arxiv_query(TITLE))
        self.assertIn("max_results=3", E.arxiv_query(TITLE))

    def test_the_lookup_switch_is_off_by_default(self):
        self.assertFalse(O.lookup_setting(None))
        self.assertFalse(O.lookup_setting({"collect_originals": True}))
        self.assertTrue(O.lookup_setting({"lookup_originals": True}))

    def test_the_cap_rises_only_after_72_hours_of_waiting(self):
        self.assertEqual(E.credit_cap(None, 3.0), 3.0)
        self.assertEqual(E.credit_cap(timedelta(hours=71), 3.0), 3.0)
        self.assertEqual(E.credit_cap(timedelta(hours=73), 3.0), 6.0)
        self.assertEqual(O.credit_after(2.5, 300, cap=6.0), 5.5)

    def test_a_paper_page_is_an_article_for_collect_originals(self):
        self.assertEqual(O.trigger_kind(PAPER, owner=None, names_account=True, reads=O.SiteReads(), article=True), O.PAGE)
        from insight_core.utils.discover_rules import app_address, archive_address, document_address, reference_address
        self.assertFalse(any(t(PAPER) for t in (archive_address, app_address, document_address, reference_address)))

    def test_sites_that_supply_three_originals_in_30_days(self):
        now = datetime(2026, 11, 9, tzinfo=timezone.utc)
        rows = [("summaries.example", f"https://summaries.example/p/{n}", now - timedelta(days=n)) for n in range(3)]
        rows += [("twice.example", f"https://twice.example/p/{n}", now) for n in range(2)]
        rows += [("old.example", f"https://old.example/p/{n}", now - timedelta(days=40)) for n in range(5)]
        rows += [("arxiv.org", f"https://arxiv.org/abs/2611.0000{n}", now) for n in range(4)]
        rows += [("followed.example", f"https://followed.example/p/{n}", now) for n in range(4)]
        got = E.suppliers(rows, now=now, followed={"followed.example"}, hidden=set())
        self.assertEqual(sorted(got), ["summaries.example"])
        self.assertEqual(got["summaries.example"]["n"], 3)
        self.assertEqual(E.supplier_reason(3), "the original of 3 things your sources talked about")


@requires_test_db
class _AddressCase(_Db):
    """A on the database: the entity stage writes each entity's addresses, read through merges and the current set."""

    def setUp(self):
        super().setUp()
        clear_tables(self.cur, "mx_entity_addresses")

    def say(self, pid, *ents, guide=None):
        if guide:
            schemas.set_entities_arm(self.cur, guide, allow_placeholder=True)
        task_id, _ = tasks.entities_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                             answer={"entities": []})
        repo.add_mentions(self.cur, post_id=pid, guide=repo.get_task(self.cur, task_id)["guide"], call_id=call,
                          mentions=list(ents))

    def link_text(self, pid, url, text):
        self.cur.execute("UPDATE post_links SET link_text = %s WHERE post_id = %s AND target_url = %s", (text, pid, url))

    def root(self, pid, n=0):
        return I.load_book(self.cur).root(self.entity_of(pid, n))

    def addresses(self, root):
        return {k: (v["url"], v["rule"]) for k, v in EA.of_root(self.cur, I.load_book(self.cur), root).items()}


@requires_test_db
class Addresses(_AddressCase):
    def test_the_three_rules_find_the_paper_its_links_and_a_release(self):
        a = self.post(0, T0, text="A paper is out.", links=[PAPER, CODE, DEMO, "https://summaries.example/p/nimbus"])
        self.link_text(a, "https://summaries.example/p/nimbus", TITLE)
        b = self.post(1, T0 + H, text="The same paper, discussed.")
        self.say(a, m(TITLE))
        self.say(b, m(TITLE))
        out = self.stage()
        self.assertEqual(out["addresses"]["added"], 4)
        root = self.root(a)
        self.assertEqual(self.root(b), root)
        self.assertEqual(self.addresses(root), {"paper": (PAPER, "identifier"), "code": (CODE, "identifier"),
                                                "demo": (DEMO, "identifier"),
                                                "release": ("https://summaries.example/p/nimbus", "title")})
        self.assertEqual(self.stage()["addresses"]["added"], 0, "written once")

    def test_a_sweep_past_its_deadline_stops_after_a_chunk_and_resumes_where_it_stopped(self):
        """v10.13.9: the sweep of every post keeps to the stage's budget; the next runs go on from its `after`, and
        together they find what one sweep finds."""
        import time
        from unittest import mock
        posts = []
        for n in range(4):
            pid = self.post(n % 5, T0 + n * H, text="A paper is out.", links=[PAPER.replace("01234", f"0123{n}")])
            self.say(pid, m(f"Nimbus Paper {n}", ref=f"arXiv:2611.0123{n}"))
            posts.append(pid)
        self.stage()
        clear_tables(self.cur, "mx_entity_addresses")
        self.cur.execute("SAVEPOINT once")
        once = EA.stage(self.cur, now=T0, since=None, full=True)
        self.cur.execute("SELECT entity_id::text, url FROM mx_entity_addresses")
        want = set(self.cur.fetchall())
        self.cur.execute("ROLLBACK TO SAVEPOINT once")
        self.assertEqual((once["posts"], once["done"], len(want)), (4, True, 4))
        seen, after = [], None
        with mock.patch.object(EA, "CHUNK", 1):
            while not seen or not seen[-1]["done"]:
                seen.append(EA.stage(self.cur, now=T0, since=datetime.now(timezone.utc) + D, full=not seen, after=after,
                                     deadline=time.monotonic() - 1))
                after = seen[-1]["after"]
                self.assertLess(len(seen), 10)
        self.assertEqual([o["posts"] for o in seen], [1, 1, 1, 1])     # a chunk a run, none read twice
        self.assertEqual([o["after"] for o in seen], sorted(posts)[:3] + [None])
        self.cur.execute("SELECT entity_id::text, url FROM mx_entity_addresses")
        self.assertEqual(set(self.cur.fetchall()), want)

    def test_a_front_page_is_never_an_address(self):
        a = self.post(0, T0, links=["https://nimbuslab.example/", "https://nimbuslab.example/nimbus-4"])
        self.link_text(a, "https://nimbuslab.example/", "Nimbus 4")
        self.say(a, m("Nimbus 4", type_="model"))
        self.stage()
        self.assertEqual(self.addresses(self.root(a)), {})

    def test_the_makers_page_for_a_model(self):
        url = "https://acmelabs.example/news/introducing-nimbus-4"
        a = self.post(0, T0, links=[url])
        self.link_text(a, url, "Introducing Nimbus 4 today")
        self.say(a, m("Nimbus 4", type_="model", maker="Acme Labs"))
        self.stage()
        self.assertEqual(self.addresses(self.root(a)), {"release": (url, "maker")})

    def test_a_merged_entity_reads_its_targets_addresses(self):
        a = self.post(0, T0, links=[PAPER])
        b = self.post(1, T0 + H, text="Words.")
        self.say(a, m(TITLE))
        self.say(b, m("The Nimbus Lattice Paper"))
        self.stage()
        x, y = self.entity_of(a), self.entity_of(b)
        self.assertNotEqual(x, y)
        I.merge(self.cur, I.load_book(self.cur), y, x, by="owner", automatic=False)
        book = I.load_book(self.cur)
        target = book.root(x)
        self.assertEqual(target, book.root(y))
        self.assertEqual(self.addresses(target)["paper"][0], PAPER)
        page = entity_views.entity_page(self.cur, y, now=T0 + D)
        self.assertEqual(page["original"]["url"], PAPER, "the merged one's page shows the target's original")
        self.assertEqual(page["original"]["kind"], "paper")

    def test_an_address_counts_only_while_its_post_names_the_entity_now(self):
        a = self.post(0, T0, links=[PAPER])
        self.say(a, m(TITLE))
        self.stage()
        root = self.root(a)
        self.assertIn("paper", self.addresses(root))
        self.say(a, m("Something Else Entirely", type_="other"), guide="ent-v4")
        self.assertEqual(self.addresses(root), {})


class PlatformRule(unittest.TestCase):
    """v10.13.5: rule `repo`, a platform's page of one thing whose <thing> segment is the entity's name."""

    def repo(self, url, *names):
        return E.by_repo(url, {N.key(n) for n in names}, N.key, N.squash)

    def test_a_model_hub_a_code_host_and_a_package_index(self):
        self.assertEqual(self.repo("https://huggingface.co/quillwort-ai/Laryx", "Laryx"), ("release", "quillwort-ai"))
        self.assertEqual(self.repo("https://hf.co/quillwort-ai/Laryx-2.5", "Laryx 2.5"), ("release", "quillwort-ai"))
        self.assertEqual(self.repo("https://huggingface.co/datasets/quillwort-ai/FernBench", "FernBench"),
                         ("release", "quillwort-ai"))
        self.assertEqual(self.repo("https://github.com/tarnwick/ember_sync", "Ember Sync"), ("code", "tarnwick"))
        self.assertEqual(self.repo("https://codeberg.org/tarnwick/embersync", "EmberSync"), ("code", "tarnwick"))
        self.assertEqual(self.repo("https://pypi.org/project/embersync/", "embersync"), ("package", None))
        self.assertEqual(self.repo("https://pypi.org/project/embersync/1.2.0", "embersync"), ("package", None))
        self.assertEqual(self.repo("https://www.npmjs.com/package/@tarnwick/embersync", "embersync"),
                         ("package", "tarnwick"))
        self.assertEqual(self.repo("https://crates.io/crates/embersync", "embersync"), ("package", None))

    def test_the_whole_name_only(self):
        self.assertIsNone(self.repo("https://huggingface.co/quillwort-ai/Laryx-7B-Instruct", "Laryx"),
                          "a longer name holding it (a variant) is another thing")
        self.assertIsNone(self.repo("https://huggingface.co/someone/Laryx-GGUF", "Laryx"),
                          "no build tag dropped: a third party's quantised copy is not the model's page")
        self.assertIsNone(self.repo("https://github.com/tarnwick/laryxkit", "Laryx"), "a substring")
        self.assertIsNone(self.repo("https://github.com/tarnwick/ember", "Ember Sync"), "a different name")
        self.assertIsNone(self.repo("https://github.com/tarnwick/abc", "ABC"), "a name too short names nothing")

    def test_never_a_home_page_an_org_page_a_section_or_a_file(self):
        for url in ("https://huggingface.co/Laryx", "https://github.com/laryx", "https://huggingface.co/",
                    "https://github.com/topics/laryx", "https://huggingface.co/blog/laryx",
                    "https://huggingface.co/spaces/quillwort-ai/laryx", "https://github.com/tarnwick/laryx/blob/main/x.py",
                    "https://docs.github.com/tarnwick/laryx", "https://gist.github.com/tarnwick/laryx",
                    "https://pypi.org/search/laryx", "https://pkgs.example/tarnwick/laryx"):
            self.assertIsNone(self.repo(url, "Laryx"), url)

    def test_one_owner_a_kind(self):
        rows = [("code", "https://github.com/ggwell/emberkit", "ggwell"), ("code", "https://github.com/fork1/emberkit", "fork1")]
        self.assertEqual(E.one_owner(rows, {"ggwell"}, N.squash), {"https://github.com/ggwell/emberkit"})
        self.assertEqual(E.one_owner(rows, set(), N.squash), set(), "two owners and no stated maker: neither")
        self.assertEqual(E.one_owner(rows[1:], set(), N.squash), {"https://github.com/fork1/emberkit"})
        self.assertTrue(E.owner_agrees("quillwort-ai", {"quillwort"}, N.squash), "a handle suffix aside")
        self.assertFalse(E.owner_agrees("tarnwick", {"quillwort"}, N.squash))


@requires_test_db
class PlatformAddresses(_AddressCase):
    def test_a_bare_model_page_link_is_the_models_address_and_its_owner_a_maker_candidate(self):
        url = "https://huggingface.co/quillwort-ai/Laryx"
        a = self.post(0, T0, text="New weights.", links=[url])
        self.link_text(a, url, url)   # a bare link: its words are its address
        self.say(a, m("Laryx", type_="model"))
        out = self.stage()
        root = self.root(a)
        self.assertEqual(out["addresses"]["by_rule"], {"repo": 1})
        self.assertEqual(self.addresses(root), {"release": (url, "repo")})
        self.cur.execute("SELECT owner FROM mx_entity_addresses WHERE entity_id = %s::uuid", (root,))
        self.assertEqual(self.cur.fetchall(), [("quillwort-ai",)])
        page = entity_views.entity_page(self.cur, root, now=T0 + D)
        self.assertEqual(page["original"]["url"], url)
        self.assertEqual(page["original"]["owner"], "quillwort-ai")
        self.assertEqual(page["maker_candidates"], [{"name": "quillwort-ai", "id": None, "agrees": False}])
        self.assertIsNone(page["maker"], "proposed, never asserted")

    def test_code_and_package_pages_and_the_negatives(self):
        urls = ["https://github.com/tarnwick/embersync", "https://pypi.org/project/embersync/",
                "https://github.com/tarnwick/embersync-plugins", "https://github.com/embersync"]
        a = self.post(0, T0, text="A tool.", links=urls)
        self.say(a, m("EmberSync", type_="software"))
        self.stage()
        root = self.root(a)
        self.assertEqual(self.addresses(root), {"code": (urls[0], "repo"), "package": (urls[1], "repo")})
        page = entity_views.entity_page(self.cur, root, now=T0 + D)
        self.assertIsNone(page["original"], "a repository and a package page are no original")
        self.assertEqual({x["kind"]: x["owner"] for x in page["addresses"]}, {"code": "tarnwick", "package": None})

    def test_two_owners_keep_the_stated_makers_only(self):
        mine, fork = "https://github.com/tarnwick/emberkit", "https://github.com/zzfork/emberkit"
        a = self.post(0, T0, text="A tool.", links=[fork, mine])
        self.say(a, m("Emberkit", type_="software", maker="Tarnwick"))
        self.stage()
        root = self.root(a)
        self.assertEqual(self.addresses(root), {"code": (mine, "repo")})
        page = entity_views.entity_page(self.cur, root, now=T0 + D)
        self.assertIn({"name": "tarnwick", "id": page["maker"]["id"] if page["maker"] else None, "agrees": True},
                      page["maker_candidates"])


@requires_test_db
class OlderGuide(_AddressCase):
    """Also (0138): an entity only an earlier guide named has its page with those posts, and is listed nowhere else."""

    def test_the_page_shows_the_older_posts_and_what_the_current_reading_names(self):
        a = self.post(0, T0, title="A post", text="A story about a franchise.")
        self.say(a, m("Kestrel Gadget", type_="product"))
        self.stage()
        old = self.entity_of(a)
        page = entity_views.entity_page(self.cur, old, now=T0 + D)
        self.assertTrue(page["current"])
        self.assertNotIn("older", page)
        self.say(a, m("The Kestrel Saga", type_="other"), guide="ent-v4")
        self.stage()
        page = entity_views.entity_page(self.cur, old, now=T0 + D)
        self.assertEqual((page["current"], page["posts"], page["sources"]), (False, 0, []))
        [line] = page["older"]
        self.assertEqual((line["id"], line["guide"], line["span"]), (a, "ent-v3", "Kestrel Gadget"))
        self.assertEqual([x["name"] for x in line["now"]], ["The Kestrel Saga"])

    def test_it_is_in_no_list_queue_or_edge(self):
        a = self.post(0, T0, text="Per the Orbit Filing by Acme Corp.")
        b = self.post(1, T0 + H, text="Acme Corpo said so.")
        self.say(a, m("Orbit Filing", role="source", by_name="Acme Corp"), m("Acme Corp", type_="org", role="actor"))
        self.say(b, m("Acme Corpo", type_="org", role="subject"))
        self.stage()
        doc, acme, corpo = self.entity_of(a, 0), self.entity_of(a, 1), self.entity_of(b, 0)
        I.queue_item(self.cur, kind="alias", a=min(acme, corpo), b=max(acme, corpo), proposal="same", reason="test",
                     conf=0.5, evidence={}, call_id=None, run_id=None)
        self.assertEqual(len(entity_views.queue(self.cur)["open"]), 1)
        self.assertEqual([x["name"] for x in entity_views.entity_page(self.cur, doc, now=T0 + D)["published_by"]], ["Acme Corp"])
        self.say(b, m("Something Else Entirely", type_="other"), guide="ent-v4")
        self.say(a, m("Orbit Filing", role="source"), guide="ent-v4")   # no `by`, no Acme Corp
        self.stage()
        names = {i["name"] for i in entity_views.entity_list(self.cur, now=T0 + D)["items"]}
        self.assertNotIn("Acme Corpo", names)
        self.assertEqual(entity_views.queue(self.cur)["open"], [], "an item about an entity no reading names waits")
        self.assertEqual(entity_views.entity_page(self.cur, doc, now=T0 + D)["published_by"], [],
                         "an edge's other end no reading names is not shown")


@requires_test_db
class _CollectCase(OriginalsCase):
    """B, C, D1, D2 through the services, on committed rows."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self._mx_clean)
        self._mx_clean()
        self.paper = "https://papers.oopaper.example/abs/2611.01234"
        self.d = self._source("rss", "https://d.oochand.example/feed.xml", name="Channel D")

    def _mx_clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            # DELETE, children first (a committed TRUNCATE of 30 tables waits on the disk's sync: ~25 s a test); the
            # guides and settings stay (load_guides is idempotent). TRUNCATE when a table this order misses holds a row.
            try:
                with conn.transaction():
                    for table in DELETE_ORDER:
                        cur.execute(f"DELETE FROM {table}")
            except psycopg.errors.ForeignKeyViolation:
                clear_tables(cur, MX_TABLES)
            cur.execute("DELETE FROM story_originals WHERE kind IN ('entity', 'lookup', 'classic', 'work')")
            cur.execute("DELETE FROM system_settings WHERE key = 'originals_suppliers'")
            schemas.load_guides(cur)

    def say(self, pid, *ents):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            task_id, _ = tasks.entities_task(cur, pid)
            call = repo.add_call(cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                                 answer={"entities": []})
            repo.add_mentions(cur, post_id=pid, guide=repo.get_task(cur, task_id)["guide"], call_id=call, mentions=list(ents))

    def stage(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            run_id = repo.start_run(cur, code_version="test", config={})
            out, _ = entity_stage.entities(cur, ask=decide.Ask(cur, self.now), now=self.now, run_id=run_id, since=None, full=True)
            repo.finish_run(cur, run_id, counts={"entities": out, "run": {"now": self.now.isoformat()}})
            return out

    def switch(self, **on):
        self._rows("INSERT INTO system_settings (key, value) VALUES ('scheduler_config', %s::jsonb) "
                   "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                   json.dumps({"collect_originals": True, "collect_originals_default": "on", **on}))

    def paper_html(self):
        return (f"<!DOCTYPE html><html><head><title>{TITLE}</title>"
                '<meta property="article:published_time" content="2026-11-01T06:00:00Z"/></head>'
                f"<body><article><h1>{TITLE}</h1><p>{'The abstract of the paper, its claims and its method. ' * 14}</p>"
                "</article></body></html>")

    def two_voices(self, role="subject", links=True):
        a = self._post(self.a, "https://a.oochana.example/p/nimbus", "A paper on lattices", self.now - timedelta(hours=30),
                       links=[self.paper] if links else [])
        b = self._post(self.b, "https://b.oochanb.example/p/nimbus", "Lattices, again", self.now - timedelta(hours=5))
        self.say(a, m(TITLE, role=role, by_name="Ivo Kestrel, Rena Varga"))
        self.say(b, m(TITLE, role=role))
        self.stage()
        return a, b

    def entity(self, pid):
        ((eid,),) = self._rows("SELECT entity_id::text FROM mx_mentions WHERE post_id = %s::uuid", pid)
        return eid


@requires_test_db
class Collecting(_CollectCase):
    def test_two_voices_collect_the_paper_once_and_the_page_shows_it_first(self):
        a, _ = self.two_voices()
        self.switch()
        http = FakeHttp({self.paper: self.paper_html()})
        summary = run(self.service().run(http))
        root = self.entity(a)
        self.assertEqual(summary["collect"], [{"url": self.paper, "outcome": "collected", "requests": 1, "entity_id": root}])
        self.assertEqual(http.requests, [self.paper])
        self.assertEqual(self._rows("SELECT kind, entity_id::text, outcome FROM story_originals WHERE url = %s", self.paper),
                         [("entity", root, "collected")])
        ((post_id,),) = self._rows("SELECT id::text FROM posts WHERE normalized_url = %s", self.paper)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            page = entity_views.entity_page(cur, root)
        self.assertEqual(page["original"]["post"]["id"], post_id)
        self.assertTrue(page["original"]["post"]["collected"])
        self.assertEqual(run(self.service().run(FakeHttp({})))["collect"], [], "never asked again")

    def test_one_voice_is_no_trigger_unless_its_post_leads_a_news_row(self):
        a = self._post(self.a, "https://a.oochana.example/p/nimbus", "A paper on lattices", self.now - timedelta(hours=3),
                       links=[self.paper])
        self.say(a, m(TITLE))
        self.stage()
        self.switch()
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(self.service().plan_entities(cur, self.now)[0], [])
        self._rows("INSERT INTO news_stories (id, first_at, voices, reports, shares, mentions, score) "
                   "VALUES (%s::uuid, %s, 1, 1, 0, 0, 1)", a, self.now)
        self._rows("INSERT INTO news_posts (post_id, news_id, role, voice, position) VALUES (%s::uuid, %s::uuid, 'report', 'v', 0)", a, a)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            planned, _ = self.service().plan_entities(cur, self.now)
        self.assertEqual([(p["url"], p["kind"], p["voices"]) for p in planned], [(self.paper, O.PAGE, 1)])

    def test_a_switched_off_voice_lists_no_page_for_discover_but_still_collects(self):
        """Issue 0200: Discover's Pages (`listing`) count no source switched off: one voice left, no trigger. The
        collection (the originals of what your sources talk about, not a suggestion) is unchanged."""
        self.two_voices()
        self.switch()
        self._rows("UPDATE sources SET enabled = false WHERE id = %s::uuid", self.b)
        self.addCleanup(self._rows, "UPDATE sources SET enabled = true WHERE id = %s::uuid", self.b)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual([w["url"] for w in self.service().plan_entities(cur, self.now, listing=True)[0]], [])
            self.assertEqual([p["url"] for p in self.service().plan_entities(cur, self.now)[0]], [self.paper])
        self._rows("UPDATE sources SET enabled = true WHERE id = %s::uuid", self.b)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual([w["url"] for w in self.service().plan_entities(cur, self.now, listing=True)[0]], [self.paper])

    def test_source_and_recommended_roles_never_trigger(self):
        for role in ("source", "recommended"):
            with self.subTest(role=role):
                self._mx_clean()
                self._rows("DELETE FROM posts WHERE url LIKE 'https://_.oochan_.example/p/nimbus'")
                self.two_voices(role=role)
                self.switch()
                with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
                    self.assertEqual(self.service().plan_entities(cur, self.now), ([], []))

    def test_after_the_news_stories_originals_within_the_credit(self):
        self.two_voices()
        self.switch()
        planned = []

        async def fake_collect(plan, http, left, now):
            planned.extend(c.get("record", "collect") for c in plan)
            return []
        service = self.service(budget=1)
        service.plan_collect = lambda cur, now: [{"url": "https://essays.ooessay.example/x", "story_id": None, "voices": 9,
                                                  "first_at": now, "kind": O.PAGE, "title": None, "quoted": None}]
        service._collect = fake_collect
        run(service.run(FakeHttp({})))
        self.assertEqual(planned, ["collect", "entity"], "0123's first, then the entities'")

    def test_the_lookup_is_off_by_default_and_on_finds_by_title_and_author(self):
        a, _ = self.two_voices(links=False)
        self.switch()
        http = FakeHttp({})
        summary = run(self.service().run(http))
        self.assertEqual((summary["lookup_on"], summary["lookup"], http.requests), (False, [], []))
        self.switch(lookup_originals=True)
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2611.07777v1</id>'
                f'<title>{TITLE}</title><author><name>Ivo Kestrel</name></author></entry></feed>')
        http = FakeHttp({E.arxiv_query(TITLE): atom})
        summary = run(self.service().run(http))
        root = self.entity(a)
        found = normalize_url("https://arxiv.org/abs/2611.07777")
        self.assertEqual(summary["lookup"], [{"entity_id": root, "outcome": "found", "url": found, "requests": 1}])
        self.assertEqual(self._rows("SELECT url, rule, kind FROM mx_entity_addresses WHERE entity_id = %s::uuid", root),
                         [(found, "lookup", "paper")])
        self.assertEqual(self._rows("SELECT outcome FROM story_originals WHERE kind = 'lookup' AND url = %s", f"entity:{root}"),
                         [("found",)])
        self._rows("DELETE FROM posts WHERE normalized_url = %s", found)

    def test_a_lookup_with_no_match_is_not_found_once(self):
        a, _ = self.two_voices(links=False)
        self.switch(lookup_originals=True)
        http = FakeHttp({E.arxiv_query(TITLE): '<feed xmlns="http://www.w3.org/2005/Atom"></feed>',
                         E.crossref_query(TITLE): {"message": {"items": []}}})
        summary = run(self.service().run(http))
        self.assertEqual([x["outcome"] for x in summary["lookup"]], ["not_found"])
        self.assertEqual(len(http.requests), 2)
        self.assertEqual(run(self.service().run(FakeHttp({})))["lookup"], [], "never asked again")

    def test_pages_list_entity_originals_until_stored(self):
        from insight_core.db import repo_discover
        a, _ = self.two_voices()
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            rows = repo_discover.entity_pages(cur, db_url(), self.now, hidden=set(), names=lambda s: "N", skip=set())
        [row] = rows
        self.assertEqual((row["url"], row["entity"]["id"], row["voices"], row["stories"]), (self.paper, self.entity(a), 2, []))
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            hidden = repo_discover.entity_pages(cur, db_url(), self.now, hidden={row["hide_key"]}, names=lambda s: "",
                                                skip=set())
        self.assertEqual(hidden, [])
        self.switch()
        run(self.service().run(FakeHttp({self.paper: self.paper_html()})))
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(repo_discover.entity_pages(cur, db_url(), self.now, hidden=set(), names=lambda s: "",
                                                        skip=set()), [], "collected: gone by itself")

    def test_a_site_of_three_originals_in_30_days_is_kept_for_discover(self):
        for n in range(3):
            self._rows("INSERT INTO story_originals (kind, url, asked_at, requests, outcome) VALUES ('collect', %s, %s, 1, 'collected')",
                       f"https://summaries.oosumms.example/p/{n}", self.now - timedelta(days=n))
            self._rows("INSERT INTO story_originals (kind, url, asked_at, requests, outcome) VALUES ('collect', %s, %s, 1, 'collected')",
                       f"https://papers.oopaper.example/abs/2611.0000{n}", self.now)
        self._rows("INSERT INTO story_originals (kind, url, asked_at, requests, outcome) VALUES ('collect', %s, %s, 0, 'walled')",
                   "https://walls.oowalls.example/p/1", self.now)
        from insight_core.db import repo_discover
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(self.service().keep_suppliers(cur, self.now), {"current": 1, "suggested": 1})
            kept = repo_discover.suppliers(cur)
        self.assertEqual(list(kept["current"]), ["summaries.oosumms.example"])
        self.assertEqual(kept["current"]["summaries.oosumms.example"]["n"], 3)
        self._rows("DELETE FROM story_originals WHERE url LIKE %s OR url LIKE %s", "https://%.oo_____.example/%",
                   "https://papers.oopaper.example/%")


class WorkRules(unittest.TestCase):
    """E2 and E5's pure rules, E1's switch."""

    def test_a_front_page_and_a_site_word(self):
        self.assertTrue(E.front_page("https://nimbus-2030.example/"))
        self.assertFalse(E.front_page("https://nimbus-2030.example/race"))
        self.assertEqual(E.site_word("https://www.nimbus-2030.example/"), "nimbus2030")

    def test_a_documents_work_site(self):
        names = {N.key("Nimbus 2030")}
        self.assertEqual(E.by_site("https://nimbus-2030.example/", None, names, N.key, N.squash), E.SITE)
        self.assertEqual(E.by_site("https://forecasts.example/", "Nimbus 2030 | A Forecast", names, N.key, N.squash), E.TITLE)
        self.assertIsNone(E.by_site("https://nimbus-2030.example/race", None, names, N.key, N.squash), "not a front page")
        self.assertIsNone(E.by_site("https://other.example/", "Other", names, N.key, N.squash))

    def test_never_a_products_or_an_apps_front_page(self):
        never = {"localrunner": {"software"}, "nimbus2030": {"document"}}
        self.assertFalse(E.work_front_allowed("https://localrunner.example/", never))
        self.assertTrue(E.work_front_allowed("https://nimbus-2030.example/", never))
        self.assertTrue(E.work_front_allowed("https://unnamed.example/", never))

    def test_store_classics_is_on_by_default(self):
        self.assertTrue(O.classics_setting(None))
        self.assertFalse(O.classics_setting({"store_classics": False}))


@requires_test_db
class WorkAddresses(_AddressCase):
    def test_a_documents_front_page_is_its_work_a_models_never(self):
        front, product = "https://nimbus-2030.example/", "https://localrunner.example/"
        a = self.post(0, T0, links=[front, product])
        self.say(a, m("Nimbus 2030"), m("Localrunner", type_="software"))
        self.stage()
        self.assertEqual(self.addresses(self.root(a, 0)), {"work": (front, "site")})
        self.assertEqual(self.addresses(self.root(a, 1)), {})


@requires_test_db
class Backfill(_CollectCase):
    """E1 and E2 through the service: the allowance, one host at a time, recorded once."""

    def setUp(self):
        super().setUp()
        self.front = "https://nimbs.oonimbs.example/"
        self.addCleanup(self._rows, "DELETE FROM classics WHERE target_url LIKE %s", "https://%.oo_____.example/%")

    def html(self, title):
        return (f"<!DOCTYPE html><html><head><title>{title}</title></head><body><article><h1>{title}</h1>"
                f"<p>{'A long read with its argument, its evidence and its conclusion. ' * 14}</p></article></body></html>")

    def work(self, also_product=False):
        pages = [self.front.rstrip("/") + "/race", self.front.rstrip("/") + "/research/forecast"]
        a = self._post(self.a, "https://a.oochana.example/p/nimbs", "A forecast", self.now - timedelta(hours=8),
                       links=[self.front, pages[0]])
        b = self._post(self.b, "https://b.oochanb.example/p/nimbs", "The forecast", self.now - timedelta(hours=4),
                       links=[self.front, pages[1]])
        self.say(a, m("Oo Nimbs"))
        self.say(b, m("Oo Nimbs"))
        if also_product:
            c = self._post(self.c, "https://c.oochanc.example/p/nimbs", "An app", self.now - timedelta(hours=2))
            self.say(c, m("OoNimbs", type_="product"))
        self.stage()
        return pages

    def test_a_work_site_is_collected_with_its_linked_pages_one_at_a_time(self):
        pages = self.work()
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            planned = [c["url"] for c in self.service().plan_works(cur, self.now, lambda url, *a: O.PAGE)]
        self.assertEqual(planned, [self.front] + sorted(pages), "the work site, then its pages your posts link")
        slept = []

        async def sleep(s):
            slept.append(s)
        http = FakeHttp({self.front: self.html("Oo Nimbs"), pages[0]: self.html("Race"), pages[1]: self.html("Forecast")})
        service = self.service()
        service.sleep = sleep
        summary = run(service.run(http))
        self.assertEqual([(c["url"], c["outcome"]) for c in summary["collect"]], [(self.front, "collected")],
                         "the front page is the document's original: B collects it under the credit")
        works = [b for b in summary["backfill"] if b.get("as") == "work"]
        self.assertEqual([w["url"] for w in works], sorted(pages), "then its pages your posts link")
        self.assertEqual({w["outcome"] for w in works}, {"collected"})
        self.assertEqual(slept, [E.PAGE_DELAY_S], "one at a time, apart")
        self.assertEqual(self._rows("SELECT count(*) FROM story_originals WHERE kind = 'work'"), [(2,)])
        ((meta,),) = self._rows("SELECT metadata FROM posts WHERE normalized_url = %s", sorted(pages)[0])
        self.assertEqual(meta["collected_as"], "work")
        self.assertEqual(run(self.service().run(FakeHttp({})))["backfill"], [], "never asked again")
        self._rows("DELETE FROM posts WHERE url LIKE %s", "https://nimbs.oonimbs.example/%")

    def test_never_a_front_page_a_product_is_named_by(self):
        self.work(also_product=True)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(self.service().plan_works(cur, self.now, lambda url, *a: O.PAGE), [])

    def test_classics_not_stored_are_collected_within_the_allowance(self):
        url = "https://essays.ooessay.example/2014/07/a-long-read"
        self._rows("INSERT INTO classics (target_url, voices, first_at, last_at, title) VALUES (%s, 4, %s, %s, 'A long read')",
                   url, self.now - timedelta(days=90), self.now - timedelta(days=5))
        self.switch(store_classics=False)
        self.assertEqual(run(self.service().run(FakeHttp({url: self.html("A long read")})))["backfill"], [], "switched off")
        self.switch()
        for n in range(E.CLASSICS_DAILY):
            self._rows("INSERT INTO story_originals (kind, url, asked_at, requests, outcome) VALUES ('classic', %s, %s, 1, 'collected')",
                       f"https://used.oousedx.example/{n}", self.now - timedelta(hours=2))
        self.assertEqual(run(self.service().run(FakeHttp({url: self.html("A long read")})))["backfill"], [], "the day's allowance spent")
        self._rows("DELETE FROM story_originals WHERE url LIKE %s", "https://used.oousedx.example/%")
        summary = run(self.service().run(FakeHttp({url: self.html("A long read")})))
        self.assertEqual(summary["backfill"], [{"url": url, "outcome": "collected", "requests": 1, "as": "classic"}])
        ((meta,),) = self._rows("SELECT metadata FROM posts WHERE normalized_url = %s", url)
        self.assertEqual(meta["collected_as"], "classic")
        self._rows("DELETE FROM story_originals WHERE url = %s", url)


@requires_test_db
class LongReads(_CollectCase):
    """F1-F3: a curated long-read's references, a followed source's missed pages, the sites long-reads cite."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self._rows, "DELETE FROM story_originals WHERE kind IN ('reference', 'missed')")
        self.addCleanup(self._rows, "DELETE FROM system_settings WHERE key = 'longread_citations'")

    def html(self, title):
        return (f"<!DOCTYPE html><html><head><title>{title}</title></head><body><article><h1>{title}</h1>"
                f"<p>{'A piece of reporting with its sources, its quotes and its numbers. ' * 14}</p></article></body></html>")

    def longread(self, n_links=9, opened=True, kind="commentary", tag="", hosts=None):
        hosts = hosts or [f"cited{n}.ooref{chr(97 + n % 26)}x.example" for n in range(n_links)]
        links = [f"https://{h}/2026/11/a-piece{tag}-{n}" for n, h in enumerate(hosts)]
        pid = self._post(self.c, f"https://c.oochanc.example/p/theme{tag}", f"A theme long-read{tag}",
                         self.now - timedelta(days=1), links=links)
        self._rows("UPDATE posts SET content = %s WHERE id = %s::uuid", "A long argument. " * 600, pid)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            task_id, _ = tasks.entities_task(cur, pid)
            call = repo.add_call(cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer={})
            repo.add_reading(cur, post_id=pid, guide="read-v2", call_id=call, kind=kind, events="one", lang="en",
                             headline="A theme", reading={"kind": kind, "events": "one"})
            if opened:
                cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened')", (pid,))
        return pid, links

    def test_an_opened_long_reads_references_are_collected_once(self):
        pid, links = self.longread()
        http = FakeHttp({u: self.html(f"Piece {n}") for n, u in enumerate(links)})
        summary = run(self.service().run(http))
        refs = [b for b in summary["backfill"] if b.get("as") == "reference"]
        self.assertEqual(sorted(r["url"] for r in refs), sorted(links))
        self.assertEqual({r["outcome"] for r in refs}, {"collected"})
        self.assertEqual(self._rows("SELECT DISTINCT from_post_id::text FROM story_originals WHERE kind = 'reference'"), [(pid,)])
        self.assertEqual(run(self.service().run(FakeHttp({})))["backfill"], [], "never asked again")
        for u in links:
            self._rows("DELETE FROM posts WHERE normalized_url = %s", u)

    def test_not_opened_short_or_a_report_is_no_curated_long_read(self):
        self.longread(opened=False)
        self.longread(n_links=7, tag="-few")
        self.longread(kind="report", tag="-news")
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(self.service().longreads(cur), {})

    def test_a_followed_sources_page_its_feed_missed_is_read_as_its_post(self):
        from insight_core.tests.test_story_originals import LAB
        missed = f"{LAB}/news/the-missed-piece"
        self._post(self.b, "https://b.oochanb.example/p/missed", "A post linking the lab", self.now - timedelta(days=2),
                   links=[missed])
        summary = run(self.service().run(FakeHttp({missed: self.html("The missed piece")})))
        self.assertIn({"url": missed, "outcome": "collected", "requests": 1}, summary["backfill"])
        ((source_id, meta),) = self._rows("SELECT source_id::text, metadata FROM posts WHERE normalized_url = %s", missed)
        self.assertEqual(source_id, self.lab, "one post under the source (0122's rule)")
        self.assertIn("missed_by_feed", meta)
        self.assertEqual(self._rows("SELECT source_id::text FROM story_originals WHERE kind = 'missed' AND url = %s", missed),
                         [(self.lab,)])

    def test_sites_the_long_reads_you_read_cite_are_kept_for_discover(self):
        from insight_core.db import repo_discover
        shared = ["shared.oocitedx.example"] * 2 + [f"other{n}.oorefa{chr(97 + n)}.example" for n in range(7)]
        self.longread(tag="-one", hosts=shared)
        self.longread(tag="-two", hosts=["shared.oocitedx.example"] + [f"more{n}.oorefb{chr(97 + n)}.example" for n in range(8)])
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.service().keep_cited(cur)
            cited = repo_discover.longread_citations(cur)
        self.assertEqual(cited.get("shared.oocitedx.example"), {"n": 3, "posts": 2})

    def test_a_switched_off_sources_long_reads_cite_nothing_for_discover(self):
        """Issue 0200: Discover's citations never count a source the owner switched off; collecting its references
        (membership, not a suggestion) still reads it."""
        from insight_core.db import repo_discover
        shared = ["shared.oocitedy.example"] * 2 + [f"other{n}.oorefc{chr(97 + n)}.example" for n in range(7)]
        pid, _ = self.longread(tag="-off", hosts=shared)
        self._rows("UPDATE sources SET enabled = false WHERE id = %s::uuid", self.c)
        self.addCleanup(self._rows, "UPDATE sources SET enabled = true WHERE id = %s::uuid", self.c)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.service().keep_cited(cur)
            self.assertNotIn("shared.oocitedy.example", repo_discover.longread_citations(cur))
            self.assertIn(pid, self.service().longreads(cur))
        self._rows("UPDATE sources SET enabled = true WHERE id = %s::uuid", self.c)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.service().keep_cited(cur)
            self.assertEqual(repo_discover.longread_citations(cur).get("shared.oocitedy.example"), {"n": 2, "posts": 1})


if __name__ == "__main__":
    unittest.main()
