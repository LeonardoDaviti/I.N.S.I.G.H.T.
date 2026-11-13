"""0162 (Stealth v10.14): research. Each seed kind; step 1 with every version of an address; the same announcement by a
unique shared link and by a near-copy; the maker from platform addresses; declared links followed two hops, same
identity only, never a link inside someone else's post; the same-identity rules and the `identity` task's schema,
validation and answer; the channels through the finder into the scratch area (nothing followed); the paper index by
exact ids (a namesake's paper left out); discussion hits exact only; the web search off until configured, a pluggable
provider; "Watch this" makes a track; the provenance; the cost guard; a run never starts by itself. Every request is
stubbed. Synthetic names only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.ingestion.http import HttpError
from insight_core.markx import research, schemas, scout, scout_reads, tracks, validate
from insight_core.markx import research_web as W
from insight_core.tests._db import clear_tables, db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_markx_api import _Api, call
from insight_core.tests.test_markx_scout import SCOUT_TABLES, StubReader, feed_result

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)
RESEARCH_TABLES = ("mx_research_pairs", "mx_research_findings", "mx_research_runs")
PAPER = "2606.13843"


def page(title, *links, me=(), text="", description=""):
    anchors = "".join(f'<a href="{u}">{u}</a>' for u in links)
    rels = "".join(f'<a rel="me" href="{u}">me</a>' for u in me)
    return (f'<html><head><title>{title}</title><meta name="description" content="{description}"></head>'
            f'<body><nav><a href="/pricing">Pricing</a><a href="/models">Models</a></nav>{rels}{anchors}<p>{text}</p>'
            f'</body></html>')


def rss_items(*items):
    body = "".join(f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
                   f"<pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate></item>" for t, u, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>search</title>{body}</channel></rss>'


# A small world of pages: a model page on a hub, its maker's hub account, code account and repository, its site, and
# accounts the site declares; one X account unreadable; a third party's post and article linked along the way.
WORLD = {
    "https://huggingface.co/acmeai/widget-1": page(
        "acmeai/widget-1", "https://github.com/acmeai/widget", "https://acme.example/",
        "https://x.com/somebody_else/status/123", "https://huggingface.co/acmeai"),
    "https://huggingface.co/acmeai": page("acmeai (Acme AI)", "https://github.com/acmeai", "https://acme.example/"),
    "https://github.com/acmeai/widget": page("acmeai/widget", "https://huggingface.co/acmeai/widget-1"),
    "https://github.com/acmeai": page("acmeai", "https://acme.example/", me=("https://x.com/acmeai_lab",)),
    "https://acme.example/": page("Acme AI", "https://huggingface.co/acmeai", "https://x.com/acmeai_lab",
                                  "https://www.youtube.com/@acmechannel", "https://news.example/2026/10/acme-raises-money"),
    "https://www.youtube.com/@acmechannel": page("Acme AI - YouTube", "https://acme.example/"),
    "https://x.com/acmeai_lab": HttpError("refused", status=403),
}


def identity_answer(same="yes", conf=0.9):
    return {"id": "x", "same": same, "confidence": conf, "why": "B's profile links A's site."}


def websearch_answer(*urls, queries=('"acmeai"', '"acmeai" site:reddit.com')):
    return {"candidates": [{"url": u, "title": "Acme AI", "why": "the result names the widget model"} for u in urls],
            "queries": list(queries)}


class FakeIndex:
    """A paper index stand-in: the seed's record, its references (one held), a citing paper, a newer one."""
    name = "fake"

    def __init__(self):
        self.calls = []

    async def work(self, http, ref):
        self.calls.append(("work", ref))
        return {"id": "https://openalex.org/W1", "doi": f"https://doi.org/10.48550/arxiv.{PAPER}",
                "display_name": "A study of example interfaces", "publication_date": "2026-06-11",
                "authorships": [{"author": {"id": "https://openalex.org/A1", "display_name": "Ann Example"}}]}

    async def references(self, http, work):
        self.calls.append(("references", work["id"]))
        return [W.short_work({"doi": "https://doi.org/10.48550/arxiv.2501.00001", "display_name": "Held ref"}),
                W.short_work({"doi": "https://doi.org/10.1145/12345", "display_name": "Not held ref"})]

    async def citing(self, http, work):
        self.calls.append(("citing", work["id"]))
        return [W.short_work({"doi": "https://doi.org/10.48550/arxiv.2609.00002", "display_name": "A citing paper"})]

    async def newer(self, http, work):
        self.calls.append(("newer", work["id"]))
        return [dict(W.short_work({"doi": "https://doi.org/10.48550/arxiv.2610.00003", "display_name": "Newer"}),
                     why="shares co-authors")]


# ---- no database -----------------------------------------------------------------------------------------------------

class Pure(unittest.TestCase):
    def test_each_seed_kind(self):
        self.assertEqual(research.seed_kind(str(uuid.uuid4())), "entity")
        self.assertEqual(research.seed_kind("https://huggingface.co/acmeai/widget-1"), "link")
        self.assertEqual(research.seed_kind("We launched Widget today!\nhttps://bit.example/x1"), "post")
        self.assertEqual(research.seed_kind("who makes the widget model?"), "question")
        self.assertEqual(research.seed_kind("Widget"), "name")
        self.assertEqual(research.seed_links("post", "see https://a.example/x, and https://b.example/y."),
                         ["https://a.example/x", "https://b.example/y"])

    def test_the_identity_kind(self):
        self.assertEqual((schemas.KINDS["identity"].guide, schemas.KINDS["identity"].subject), ("identity-v1", "research_pair"))
        self.assertIn("A shared name alone is NOT enough", schemas.guide_body("identity-v1"))
        self.assertIsNone(validate.check("identity", identity_answer(), "q")[1])
        self.assertIsNone(validate.check("identity", identity_answer("unsure", 0.3), "q")[1])
        self.assertIsNotNone(validate.check("identity", dict(identity_answer(), same="maybe"), "q")[1])
        self.assertIsNotNone(validate.check("identity", dict(identity_answer(), confidence=3), "q")[1])
        self.assertIn("one line", validate.check("identity", dict(identity_answer(), why="a\nb"), "q")[1])
        self.assertIsNotNone(validate.check("identity", {"same": "yes"}, "q")[1])

    def test_the_websearch_kind(self):
        """0171: the worker's web search: its guide (a name alone is not enough, no fetching), schema and checks."""
        self.assertEqual((schemas.KINDS["websearch"].guide, schemas.KINDS["websearch"].subject),
                         ("websearch-v1", "research_run"))
        body = schemas.guide_body("websearch-v1")
        self.assertIn("A shared name alone is NOT enough", body)
        self.assertIn("Never open or fetch pages", body)
        ok = websearch_answer("https://x.com/acmeai_team")
        self.assertIsNone(validate.check("websearch", ok, "q")[1])
        self.assertIsNone(validate.check("websearch", {"candidates": [], "queries": []}, "q")[1])   # nothing found
        bad = [({"candidates": []}, "queries"),
               (dict(ok, queries=["a", "b", "c", "d", "e", "f"]), "more than 5"),             # the run's cap
               (dict(ok, candidates=[{"url": "ftp://x.example/a", "why": "w"}]), "http(s)"),
               (dict(ok, candidates=[{"url": "https://a.example/ b", "why": "w"}]), "no spaces"),
               (dict(ok, candidates=[{"url": "https://a.example/", "why": "w"},
                                     {"url": "https://www.a.example", "why": "w"}]), "twice"),
               (dict(ok, candidates=[{"url": "https://a.example/", "why": "a\nb"}]), "one line"),
               (dict(ok, candidates=[{"url": "https://a.example/", "why": "  "}]), "why"),
               (dict(ok, candidates=[{"url": "https://a.example/"}]), "why"),
               (dict(ok, candidates=[{"url": "https://a.example/" + "a" * 600, "why": "w"}]), "500"),
               (dict(ok, queries=["a\nb"]), "one line")]
        for answer, says in bad:
            with self.subTest(answer=answer):
                err = validate.check("websearch", answer, "q")[1]
                self.assertIsNotNone(err)
                self.assertIn(says, err)

    def test_classify_by_platform_class(self):
        c = W.classify
        self.assertEqual(c("https://github.com/acmeai/widget")["kind"], "project")
        self.assertEqual(c("https://github.com/acmeai/widget")["owner"], "acmeai")
        self.assertEqual(c("https://github.com/acmeai")["key"], "github.com/acmeai")
        self.assertIsNone(c("https://github.com/pricing"))                     # the platform's own page
        self.assertEqual(c("https://x.com/acmeai_lab")["key"], "x.com/acmeai_lab")
        self.assertIsNone(c("https://x.com/somebody_else/status/123"))         # someone's post: no identity
        self.assertIsNone(c("https://news.example/2026/10/acme-raises-money"))  # someone's article: no identity
        self.assertEqual(c(f"https://arxiv.org/pdf/{PAPER}v2")["key"], f"paper:{PAPER}")
        self.assertEqual(c("https://acme.example/")["kind"], "site")
        self.assertIsNone(c("https://twitter.com/intent/tweet?url=x"))

    def test_declared_links_are_the_pages_own(self):
        url = "https://huggingface.co/acmeai/widget-1"
        got = W.page_summary(WORLD[url], url)
        self.assertEqual(got["title"], "acmeai/widget-1")
        self.assertEqual(got["links"], ["https://github.com/acmeai/widget", "https://acme.example/",
                                        "https://huggingface.co/acmeai"])   # no nav, no one else's post
        me = W.page_summary(WORLD["https://github.com/acmeai"], "https://github.com/acmeai")["links"]
        self.assertEqual(me[0], "https://x.com/acmeai_lab")                    # rel=me first

    def test_the_same_identity_rules(self):
        def acc(url, links=(), read=True, text="", handles=()):
            return dict(W.classify(url), links=list(links), read=read, text=text, handles=list(handles))
        model = acc("https://huggingface.co/acmeai/widget-1")
        owner = acc("https://huggingface.co/acmeai")
        self.assertEqual(W.same_identity(model, owner), ("yes", "the platform says this account owns it"))
        a = acc("https://github.com/acmeai", links=["https://acme.example/"])
        site = acc("https://acme.example/", links=["https://github.com/acmeai"])
        self.assertEqual(W.same_identity(a, site)[0], "yes")                   # each links the other
        hub = acc("https://huggingface.co/acmeai", links=["https://github.com/acmeai"])
        self.assertEqual(W.same_identity(hub, acc("https://github.com/acmeai", read=False))[1],
                         "the same handle, and one links the other")
        self.assertEqual(W.same_identity(a, acc("https://x.com/acmeai_lab", text="We build at github.com/acmeai"))[0], "yes")
        # a namesake: the same name and title, nothing that ties them
        namesake = acc("https://x.com/acme_other", text="Acme AI: physics and amplitudes", handles=["acme_other"])
        self.assertEqual(W.same_identity(a, namesake)[0], None)
        self.assertEqual(W.same_identity(a, acc("https://x.com/acme_ai", read=False)),
                         (None, "its page could not be read"))

    def test_every_version_of_an_address(self):
        exact, prefixes = W.versions(f"https://arxiv.org/html/{PAPER}v3")
        for u in (f"https://arxiv.org/abs/{PAPER}", f"https://arxiv.org/abs/{PAPER}v2", f"https://arxiv.org/pdf/{PAPER}v1",
                  f"https://arxiv.org/pdf/{PAPER}.pdf", f"https://doi.org/10.48550/arXiv.{PAPER}"):
            self.assertIn(u, exact)
        _, prefixes = W.versions("https://github.com/acmeai/widget")
        self.assertEqual(prefixes, ["https://github.com/acmeai/widget/"])      # its releases, tags and files

    def test_a_discussion_hit_is_exact(self):
        hit = W.exact_hit
        self.assertEqual(hit({"title": f"Paper arXiv:{PAPER}v2 is out"}, terms=[PAPER], addresses=[], title=None),
                         f"contains {PAPER}")
        self.assertIsNone(hit({"title": "Paper 2406.13843 is out"}, terms=[PAPER], addresses=[], title=None))
        self.assertIsNone(hit({"title": f"{PAPER}1 a longer id"}, terms=[PAPER], addresses=[], title=None))
        self.assertEqual(hit({"text": "see github.com/acmeai/widget"}, terms=[], addresses=["https://github.com/acmeai/widget"],
                             title=None), "links github.com/acmeai/widget")
        self.assertEqual(hit({"title": "Re: A study of example interfaces"}, terms=[], addresses=[],
                             title="A study of example interfaces"), "carries its exact title")
        self.assertIsNone(hit({"title": "A study of example widgets"}, terms=[], addresses=[],
                              title="A study of example interfaces"))
        self.assertEqual(W.id_terms("https://github.com/acmeai/widget"), ["acmeai/widget"])

    def test_the_open_paper_index_by_exact_ids_and_the_namesake_left_out(self):
        base = "https://index.example"
        work = {"id": "https://openalex.org/W1", "doi": f"https://doi.org/10.48550/arxiv.{PAPER}", "display_name": "Seed",
                "publication_date": "2026-06-11", "primary_topic": {"field": {"id": "F17"}},
                "authorships": [{"author": {"id": "https://openalex.org/A1", "display_name": "Ann Example"}},
                                {"author": {"id": "https://openalex.org/A2", "display_name": "Bo Example"}}]}
        newer = {"results": [
            {"id": "W2", "doi": "https://doi.org/10.48550/arxiv.2610.00003", "display_name": "With a co-author",
             "authorships": [{"author": {"id": "https://openalex.org/A1"}}, {"author": {"id": "https://openalex.org/A2"}}]},
            {"id": "W3", "doi": "https://doi.org/10.1103/phys.1", "display_name": "A namesake's physics paper",
             "primary_topic": {"field": {"id": "F31"}}, "authorships": [{"author": {"id": "https://openalex.org/A1"}}]},
            {"id": "W4", "doi": "https://doi.org/10.1145/same.field", "display_name": "Same author, same field",
             "primary_topic": {"field": {"id": "F17"}}, "authorships": [{"author": {"id": "https://openalex.org/A2"}}]}]}

        def answer(url):
            if "/works/doi:" in url:
                return json.dumps(work)
            if "author.id" in url:
                return json.dumps(newer)
            if "cited_by:W1" in url:
                return json.dumps({"results": [{"doi": "https://doi.org/10.1145/12345", "display_name": "A ref"}]})
            if "cites:W1" in url:
                return json.dumps({"results": []})
            raise HttpError("no", status=404)
        http = FakeHttp(answer)
        index = W.OpenAlex(base)
        got = asyncio.run(index.work(http, f"arXiv:{PAPER}"))
        self.assertEqual(got["id"], "https://openalex.org/W1")
        self.assertIn(f"/works/doi:10.48550/arXiv.{PAPER}", http.requests[0])
        self.assertEqual([r["ref"] for r in asyncio.run(index.references(http, got))], ["doi:10.1145/12345"])
        kept = asyncio.run(index.newer(http, got))
        self.assertEqual([r["title"] for r in kept], ["With a co-author", "Same author, same field"])
        self.assertIsNone(asyncio.run(W.OpenAlex(base).work(FakeHttp({f"{base}/works/doi:10.48550/arXiv.2606.99999?select="
                                                                      + W.WORK_FIELDS: json.dumps(work)}), "arXiv:2606.99999")))

    def test_the_paper_index_is_behind_a_setting(self):
        cur = mock.Mock()
        with mock.patch("insight_core.markx.repo.get_setting", return_value="openalex"):
            self.assertIsInstance(W.paper_index(cur), W.OpenAlex)
        with mock.patch("insight_core.markx.repo.get_setting", return_value="off"):
            self.assertIsNone(W.paper_index(cur))

    def test_web_search_is_the_workers_until_configured_and_pluggable(self):
        with mock.patch.dict("os.environ", {W.WEB_SEARCH_URL_ENV: "", W.WEB_SEARCH_KEY_ENV: ""}):
            with mock.patch.dict("os.environ", {W.WEB_SEARCH_ENV: ""}):
                self.assertIsInstance(W.web_search(), W.WorkerSearch)          # 0171: the worker's by default
                self.assertEqual(W.web_search().name, "worker")
            with mock.patch.dict("os.environ", {W.WEB_SEARCH_ENV: "worker"}):
                self.assertIsInstance(W.web_search(), W.WorkerSearch)
            for off in ("off", "none", "OFF"):
                with mock.patch.dict("os.environ", {W.WEB_SEARCH_ENV: off}):
                    self.assertIsNone(W.web_search())                          # the owner turned it off
            with mock.patch.dict("os.environ", {W.WEB_SEARCH_ENV: "searxng", W.WEB_SEARCH_URL_ENV: ""}):
                self.assertIsInstance(W.web_search(), W.WorkerSearch)          # named but not configured: the worker's
            with mock.patch.dict("os.environ", {W.WEB_SEARCH_ENV: "brave", W.WEB_SEARCH_KEY_ENV: "k"}):
                self.assertIsInstance(W.web_search(), W.BraveSearch)
            with mock.patch.dict("os.environ", {W.WEB_SEARCH_ENV: "searxng", W.WEB_SEARCH_URL_ENV: "https://sx.example"}):
                provider = W.web_search()
        http = FakeHttp(lambda u: json.dumps({"results": [{"url": "https://x.com/acmeai_lab", "title": "Acme", "content": "c"}]}))
        got = asyncio.run(provider.search(http, '"Acme AI" site:x.com'))
        self.assertEqual(got, [{"url": "https://x.com/acmeai_lab", "title": "Acme", "snippet": "c"}])
        self.assertTrue(http.requests[0].startswith("https://sx.example/search?q="))
        brave = W.BraveSearch("secret-key", base="https://brave.example/search")
        http = FakeHttp(lambda u: json.dumps({"web": {"results": [{"url": "https://www.youtube.com/@acmechannel"}]}}))
        self.assertEqual(asyncio.run(brave.search(http, "q"))[0]["url"], "https://www.youtube.com/@acmechannel")
        self.assertEqual(http.headers_for(http.requests[0])["X-Subscription-Token"], "secret-key")
        self.assertEqual(W.web_queries("Acme AI", 3), ['"Acme AI"', '"Acme AI" site:x.com', '"Acme AI" site:youtube.com'])


# ---- on the test database ----------------------------------------------------------------------------------------------

@requires_test_db
class _Research(_Api):
    plan = True

    def setUp(self):
        super().setUp()
        tables = (*RESEARCH_TABLES, *SCOUT_TABLES, "mx_tracks", "mx_track_items")
        clear_tables(self.cur, tables, cascade=True)
        self.addCleanup(clear_tables, self.cur, tables, cascade=True)
        for target, value in ((scout, "_x_bridge"),):
            p = mock.patch.object(target, value, return_value=None)
            p.start()
            self.addCleanup(p.stop)
        for name in ("insight_core.ingestion.kinds.nitter_rss.nitter_origin",):
            p = mock.patch(name, return_value=None)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(scout, "reads_allowed", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        # the page's background advance (GET /research/{id}) reads nothing outside here: no client
        p = mock.patch.object(research, "default_tools",
                              side_effect=lambda cur: research.Tools(http=None, reader=StubReader(), index=None, search=None))
        p.start()
        self.addCleanup(p.stop)
        self.folders = []
        self.addCleanup(self._drop_folders)
        self.added = []
        self.addCleanup(self._drop_added)

    def _drop_folders(self):
        self.cur.execute("SELECT track_id::text FROM mx_research_runs WHERE track_id IS NOT NULL")
        for (fid,) in self.cur.fetchall():
            self.cur.execute("DELETE FROM source_folders WHERE folder_id = %s", (fid,))
            self.cur.execute("DELETE FROM folders WHERE id = %s", (fid,))

    def _drop_added(self):
        for sid in self.added:
            self.cur.execute("DELETE FROM source_folders WHERE source_id = %s", (sid,))
            self.cur.execute("DELETE FROM sources WHERE id = %s", (sid,))

    def add_source(self, platform, handle, settings):
        self.cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, settings) VALUES (%s, %s, true, %s::jsonb) "
                         "RETURNING id", (platform, f"{handle}#{uuid.uuid4().hex[:6]}", json.dumps(settings)))
        sid = str(self.cur.fetchone()[0])
        self.added.append(sid)
        return sid

    def entity(self, name, type_="model", maker=None):
        self.cur.execute("INSERT INTO mx_entities (type, name, key, maker, status) VALUES (%s, %s, %s, %s, 'confirmed') "
                         "RETURNING id::text", (type_, name, name.lower(), maker))
        return self.cur.fetchone()[0]

    def mention(self, post, eid, name):
        from insight_core.markx import repo
        tid, _ = repo.add_task(self.cur, kind="entities", guide="ent-v3", subject_kind="post", input=f"e {uuid.uuid4().hex}",
                               a=post)
        call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="test", valid=True, answer={})
        repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=call_id,
                          mentions=[{"span": name, "name": name, "name_key": name.lower(), "type": "model",
                                     "role": "subject"}])
        self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (eid, post))

    def start(self, seed, kind=None):
        with self.conn.transaction():
            return research.start(self.cur, seed, kind=kind)

    def tools(self, world=None, reader=None, index=None, search=None):
        return research.Tools(http=FakeHttp(world if world is not None else WORLD), reader=reader or StubReader(),
                              index=index, search=search)

    def advance(self, run_id, tools):
        return asyncio.run(research.advance(db_url(), run_id, tools=tools))

    def view(self, run_id):
        status, body = call("GET", f"/api/markx/research/{run_id}")
        self.assertEqual(status, 200, body)
        return body

    def accounts(self, run_id):
        with self.conn.transaction():
            return research._accounts(self.cur, run_id)

    def answer_pairs(self, same):
        self.cur.execute("SELECT p.task_id, p.b FROM mx_research_pairs p")
        rows = self.cur.fetchall()
        status, body = self.answer(*[(t, identity_answer(same(b))) for t, b in rows])
        self.assertEqual((status, body["valid"]), (200, len(rows)), body)
        return {b for _, b in rows}


class Seeds(_Research):
    def test_an_entity_a_name_a_link_a_post_and_a_question(self):
        e = self.entity("Widget One")
        p = self.post(title="Widget One is out", links=[(f"https://arxiv.org/pdf/{PAPER}v2", "paper")])
        self.mention(p, e, "Widget One")
        self.cur.execute("INSERT INTO mx_entity_addresses (entity_id, url, kind, rule) VALUES (%s, %s, 'paper', 'identifier')",
                         (e, f"https://arxiv.org/abs/{PAPER}"))
        status, body = call("POST", "/api/markx/research", body={"seed": e})
        self.assertEqual((status, body["seed_kind"]), (200, "entity"), body)
        page_ = self.view(body["id"])
        held = [h for h in page_["held"] if h["key"].startswith("entity:")]
        self.assertEqual((held[0]["entity"]["name"], held[0]["posts"]), ("Widget One", 1))
        linking = [h for h in page_["held"] if h["key"].startswith("post:")]
        self.assertEqual([h["post_id"] for h in linking], [p])               # its pdf v2 is the abstract's version
        self.assertEqual(self.start("Widget One")["held"]["entities"], 1)     # a name, by its key
        self.assertEqual(self.start(f"https://arxiv.org/html/{PAPER}v3")["held"]["entities"], 1)   # a link, any version
        got = self.start(f"Our paper is out: https://arxiv.org/abs/{PAPER}v1 please read")
        self.assertEqual((got["seed_kind"], got["held"]["entities"]), ("post", 1))
        with mock.patch("insight_core.markx.search.entity_cards", return_value=[{"id": e, "name": "Widget One"}]):
            q = self.start("who makes the widget one model?")
        self.assertEqual((q["seed_kind"], q["held"]["entities"]), ("question", 1))

    def test_an_unknown_name_is_proposed_as_a_new_one_and_other_names_offered(self):
        e = self.entity("Gizmo")
        self.entity("Gizmo Decision")
        got = self.start("Gizmo")
        body = self.view(got["id"])
        self.assertEqual([x["name"] for x in body["entities"]], ["Gizmo Decision"])   # may be one thing: offered
        body = self.view(self.start("Unheard Thing")["id"])
        self.assertEqual(body["entities"][0], {"name": "Unheard Thing", "proposed": True,
                                               "why": "no entity INSIGHT knows has this name", "new": True})
        self.assertIsNotNone(e)

    def test_an_empty_seed_or_unknown_entity_is_refused(self):
        self.assertEqual(call("POST", "/api/markx/research", body={"seed": " "})[0], 400)
        self.assertEqual(call("POST", "/api/markx/research", body={"seed": str(uuid.uuid4())})[0], 400)

    def test_a_run_never_starts_by_itself(self):
        self.entity("Surging Thing")
        asyncio.run(research.tick(db_url(), tools=self.tools()))
        self.cur.execute("SELECT count(*) FROM mx_research_runs")
        self.assertEqual(self.cur.fetchone()[0], 0)


class SamePost(_Research):
    def test_the_shared_unique_link_first_and_no_common_page(self):
        notebook = "https://notebooks.example/code/someone/fast-edits"
        held = self.post(title="Decision model edits weights", links=[(notebook, "notebook")])
        common = "https://docs.example/guide/getting-started"
        for k in range(research.UNIQUE_MAX + 1):
            self.post(title=f"common {k}", links=[(common, "docs")])
        seed = f"Wrote it into the weights. https://short.example/a1 https://short.example/b2"
        run = self.start(seed)
        http = FakeHttp({"https://short.example/a1": "x", "https://short.example/b2": "y"},
                        redirects={"https://short.example/a1": notebook, "https://short.example/b2": common})
        self.advance(run["id"], research.Tools(http=http, reader=StubReader(), index=None, search=None))
        body = self.view(run["id"])
        self.assertEqual([(s["post_id"], s["strength"]) for s in body["same_post"]], [(held, "link")])
        self.assertEqual(body["same_post"][0]["why"], "shares the link notebooks.example/code/someone/fast-edits")
        self.assertEqual(body["run"]["spent"]["page_requests"], 2)            # one request a link

    def test_a_near_copy_of_the_pasted_text(self):
        text = ("Decision model to edit language model weights directly without any training, released with a "
                "notebook and a preprint describing the method, its evaluation and its limits in detail today.")
        copy = self.post(title="Decision model", text=text)
        self.post(title="Other", text="Completely different words about gardening, tomatoes and watering schedules.")
        run = self.start(text + " https://short.example/a1")
        self.advance(run["id"], research.Tools(http=FakeHttp({"https://short.example/a1": "x"}), reader=StubReader(),
                                               index=None, search=None))
        got = [(s["post_id"], s["strength"]) for s in self.view(run["id"])["same_post"]]
        self.assertEqual(got, [(copy, "text")])


class Maker(_Research):
    def run_world(self, seed="https://huggingface.co/acmeai/widget-1", **kw):
        run = self.start(seed)
        self.advance(run["id"], self.tools(**kw))
        return run["id"]

    def test_maker_from_platform_addresses_and_two_hops_of_declared_links(self):
        rid = self.run_world()
        acc = self.accounts(rid)
        self.assertEqual(acc["huggingface.co/acmeai/widget-1"]["same"], "seed")
        self.assertEqual((acc["huggingface.co/acmeai"]["same"], acc["huggingface.co/acmeai"]["rule"]),
                         ("yes", "the platform says this account owns it"))
        self.assertEqual(acc["github.com/acmeai/widget"]["same"], "yes")       # each links the other
        self.assertEqual(acc["acme.example"]["same"], "yes")
        self.assertEqual(acc["github.com/acmeai"]["same"], "yes")
        self.assertEqual(acc["youtube.com/@acmechannel"]["hop"], 2)
        self.assertEqual(acc["youtube.com/@acmechannel"]["same"], "yes")       # its page links the site back
        self.assertEqual(acc["x.com/acmeai_lab"]["read"], False)
        self.assertEqual(acc["x.com/acmeai_lab"]["same"], "pending")           # unreadable: one Haiku question
        keys = set(acc)
        self.assertFalse(any("status" in k or "news.example" in k for k in keys))   # never others' posts
        self.assertTrue(all(a["hop"] <= research.HOPS for a in acc.values()))
        self.cur.execute("SELECT count(*), min(t.kind), min(t.subject_kind) FROM mx_research_pairs p JOIN mx_tasks t ON t.id = p.task_id")
        self.assertEqual(self.cur.fetchone(), (1, "identity", "research_pair"))
        self.cur.execute("SELECT status FROM mx_research_runs WHERE id = %s", (rid,))
        self.assertEqual(self.cur.fetchone()[0], "waiting")
        # Haiku's answer (the worker's) goes through tasks.record: the account is the maker's
        asked = self.answer_pairs(lambda b: "yes")
        self.assertEqual(asked, {"x.com/acmeai_lab"})
        self.assertEqual(self.accounts(rid)["x.com/acmeai_lab"]["same"], "yes")
        body = self.view(rid)
        self.assertIn("x.com/acmeai_lab", {a["key"] for a in body["maker"]["accounts"]})

    def test_a_namesake_found_by_name_is_never_the_maker_by_rule(self):
        class Search:
            name = "stub"

            async def search(self, http, q):
                return [{"url": "https://x.com/acme_other", "title": "Acme AI", "snippet": "physics"}]
        world = dict(WORLD, **{"https://x.com/acme_other": page("Acme AI", text="Acme AI: amplitudes and physics")})
        rid = self.run_world(world=world, search=Search())
        other = self.accounts(rid)["x.com/acme_other"]
        self.assertTrue(other["how"].startswith("web search"))
        self.assertEqual(other["same"], "pending")                            # asked, never yes by its name
        self.answer_pairs(lambda b: "no" if b == "x.com/acme_other" else "yes")
        body = self.view(rid)
        self.assertIn("x.com/acme_other", {a["key"] for a in body["maker"]["not_same"]})
        self.assertNotIn("x.com/acme_other", {a["key"] for a in body["maker"]["accounts"]})

    def test_channels_through_the_finder_into_the_scratch_area(self):
        self.cur.execute("SELECT count(*) FROM sources")
        before = self.cur.fetchone()[0]
        reader = StubReader(default=lambda a: feed_result(a) if "acme.example" in a else None)
        rid = self.run_world(reader=reader)
        asked = {a for a, _ in reader.asked}
        self.assertIn("https://acme.example/", asked)
        self.assertIn("https://github.com/acmeai", asked)                    # the maker's account
        self.assertIn("https://github.com/acmeai/widget", asked)             # and its project, a channel of its own
        self.assertNotIn("https://x.com/acmeai_lab", asked)                  # not confirmed yet: no channel
        body = self.view(rid)
        site = next(c for c in body["channels"]["to_follow"] if c["key"] == "acme.example")
        self.assertEqual((site["finder"], site["items"], site["reads_well"]), ("research", 20, True))
        self.assertTrue(body["channels"]["cannot"])                          # the others said why
        self.cur.execute("SELECT count(*) FROM sources")
        self.assertEqual(self.cur.fetchone()[0], before)                      # nothing followed
        # Follow (passive without a track) through the add path, provenance 'research'; then Watch this
        with mock.patch.object(scout, "default_add_source", side_effect=self.add_source):
            status, got = call("POST", f"/api/markx/research/{rid}/channels/{site['id']}/follow")
        self.assertEqual((status, got["as"]), (200, "passive"), got)
        self.cur.execute("SELECT kind, run_id::text FROM mx_source_provenance WHERE source_id = %s", (got["source_id"],))
        kind, scout_run = self.cur.fetchone()
        self.assertEqual(kind, "research")
        status, watch = call("POST", f"/api/markx/research/{rid}/watch")
        self.assertEqual((status, watch["made"]), (200, True), watch)
        track = tracks.get(self.cur, watch["track_id"])
        self.assertTrue(tracks.is_topic(track))
        self.assertIn("acmeai/widget-1", track["name"])
        self.cur.execute("SELECT source_id::text FROM source_folders WHERE folder_id = %s", (watch["track_id"],))
        self.assertEqual([r[0] for r in self.cur.fetchall()], [got["source_id"]])   # the followed channel, active
        self.cur.execute("SELECT track_id::text, as_active FROM mx_source_provenance WHERE source_id = %s", (got["source_id"],))
        self.assertEqual(self.cur.fetchone(), (watch["track_id"], True))
        self.assertEqual(call("POST", f"/api/markx/research/{rid}/watch")[1]["made"], False)   # once

    def test_the_cost_guard(self):
        with mock.patch.object(research, "PAGE_REQUESTS", 3):
            rid = self.run_world()
        self.cur.execute("SELECT page_requests FROM mx_research_runs WHERE id = %s", (rid,))
        self.assertEqual(self.cur.fetchone()[0], 3)
        body = self.view(rid)
        self.assertTrue(any("page requests are spent" in (u.get("why") or "") for u in body["unread"]))
        with mock.patch.object(research, "IDENTITY_MAX", 0):
            rid = self.run_world()
        acc = self.accounts(rid)["x.com/acmeai_lab"]
        self.assertEqual(acc["same"], "unsure")
        self.assertIn("identity questions are spent", acc["rule"])
        self.cur.execute("SELECT stats->'spent' FROM mx_research_runs WHERE id = %s", (rid,))
        self.assertEqual(self.cur.fetchone()[0]["identity_asked"], 0)


class Papers(_Research):
    def test_the_paper_index_by_exact_ids_held_or_not(self):
        held = self.post(title="A ref we hold", links=[("https://arxiv.org/pdf/2501.00001v1", "pdf")])
        index = FakeIndex()
        run = self.start(f"https://arxiv.org/abs/{PAPER}")
        self.advance(run["id"], self.tools(world={}, index=index))
        self.assertEqual([c[0] for c in index.calls], ["work", "references", "citing", "newer"])
        body = self.view(run["id"])
        refs = {p["ref"]: p["held"] for p in body["papers"]["reference"]}
        self.assertEqual(refs, {"arXiv:2501.00001": held, "doi:10.1145/12345": None})
        self.assertEqual((body["papers"]["held_references"], body["papers"]["references"]), (1, 2))
        self.assertEqual([p["ref"] for p in body["papers"]["citing"]], ["arXiv:2609.00002"])
        self.assertEqual([p["ref"] for p in body["papers"]["newer"]], ["arXiv:2610.00003"])
        self.assertIn("author:https://openalex.org/A1", {a["key"] for a in body["maker"]["accounts"]})
        self.cur.execute("SELECT paper_calls FROM mx_research_runs WHERE id = %s", (run["id"],))
        self.assertEqual(self.cur.fetchone()[0], 4)
        with mock.patch.object(research, "PAPER_CALLS", 2):
            index = FakeIndex()
            run = self.start(f"https://arxiv.org/abs/{PAPER}v2")
            self.advance(run["id"], self.tools(world={}, index=index))
        self.assertEqual(len(index.calls), 2)

    def test_discussion_hits_are_exact_only(self):
        q = f"%22{PAPER}%22"
        world = {scout.REDDIT_SEARCH.format(q=q): rss_items(
            ("We discuss it", "https://www.reddit.com/r/hci/comments/1/x", f"arXiv {PAPER}v3 is worth reading"),
            ("Another paper", "https://www.reddit.com/r/hci/comments/2/y", "arXiv 2406.13843 is unrelated")),
            scout.HN_SEARCH.format(q=PAPER): rss_items(("Nothing", "https://news.example/item?id=1", "no id here"))}
        run = self.start(f"https://arxiv.org/abs/{PAPER}")
        self.advance(run["id"], self.tools(world=world))
        body = self.view(run["id"])
        self.assertEqual([(d["url"], d["why"]) for d in body["discussion"]],
                         [("https://www.reddit.com/r/hci/comments/1/x", f"contains {PAPER}")])
        self.cur.execute("SELECT search_calls FROM mx_research_runs WHERE id = %s", (run["id"],))
        self.assertLessEqual(self.cur.fetchone()[0], research.DISCUSSION_SEARCHES)

    def test_a_rerun_shows_only_new_findings_as_new(self):
        run = self.start(f"https://arxiv.org/abs/{PAPER}")
        self.advance(run["id"], self.tools(world={}, index=FakeIndex()))
        with self.conn.transaction():
            again = research.rerun(self.cur, run["id"])
        self.advance(again["id"], self.tools(world={}, index=FakeIndex()))
        body = self.view(again["id"])
        self.assertTrue(body["papers"]["reference"])
        self.assertFalse(any(p["new"] for p in body["papers"]["reference"]))
        self.assertEqual(body["run"]["previous_id"], run["id"])
        self.assertEqual(call("POST", f"/api/markx/research/{run['id']}/rerun")[0], 200)
        self.assertEqual(call("POST", f"/api/markx/research/{uuid.uuid4()}/rerun")[0], 404)


class WebByWorker(_Research):
    """0171: the web search asked of the worker (Claude Code's web search tool on the owner's device): one `websearch`
    task a run, the run waiting until it is answered, its candidates read and judged like any other (a name alone never
    counts), the run's 5 searches spent when it is asked, the same question one task."""
    SEED = "https://huggingface.co/acmeai/widget-1"
    WEB_WORLD = dict(WORLD, **{
        "https://www.reddit.com/user/acmeai_team": page("acmeai_team", "https://acme.example/"),   # links the site
        "https://x.com/acme_other": page("Acme AI", text="Acme AI: amplitudes and physics"),       # a namesake
    })

    def setUp(self):
        super().setUp()
        async def no_discussion(*_a, **_k):        # the run's searches here are the web's only
            return {"searches": 0}
        p = mock.patch.object(research, "discussion", no_discussion)
        p.start()
        self.addCleanup(p.stop)

    def tools(self, world=None, reader=None, index=None, search="worker"):
        return super().tools(world=world if world is not None else self.WEB_WORLD, reader=reader, index=index,
                             search=W.WorkerSearch() if search == "worker" else search)

    def web_task(self, rid):
        self.cur.execute("SELECT web_task_id FROM mx_research_runs WHERE id = %s", (rid,))
        tid = self.cur.fetchone()[0]
        return tid and self.row(tid)

    def run_row(self, rid):
        self.cur.execute("SELECT status, steps, search_calls, stats FROM mx_research_runs WHERE id = %s", (rid,))
        return dict(zip(("status", "steps", "search_calls", "stats"), self.cur.fetchone()))

    def test_asked_waits_then_goes_on_with_the_candidates_judged(self):
        run = self.start(self.SEED)
        self.advance(run["id"], self.tools())
        task = self.web_task(run["id"])
        self.assertEqual((task["kind"], task["guide"], task["subject_kind"], str(task["a"]), task["status"]),
                         ("websearch", "websearch-v1", "research_run", run["id"], "open"))
        self.assertIn("Maker: acmeai", task["input"])
        self.assertIn("Confirmed as its own: ", task["input"])
        self.assertIn("https://acme.example/", task["input"])                 # tied to, and left out
        self.assertIn(f"Searches allowed: at most {research.WEB_QUERIES}", task["input"])
        row = self.run_row(run["id"])
        self.assertNotIn("web", row["steps"])                                 # waits for the worker
        self.assertEqual(row["search_calls"], research.WEB_QUERIES)          # the run's 5 searches spent when asked
        self.assertEqual(row["status"], "waiting")
        view = self.view(run["id"])
        self.assertEqual((view["run"]["web_search"]["by"], view["run"]["web_search"]["waiting"]), ("worker", True))
        # advancing again before the answer asks nothing more
        self.advance(run["id"], self.tools())
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'websearch'")
        self.assertEqual(self.cur.fetchone()[0], 1)
        self.assertEqual(self.run_row(run["id"])["search_calls"], row["search_calls"])
        # the worker's answer: an account that links the site, an article, a namesake, and one already confirmed
        status, body = self.answer((task["id"], websearch_answer(
            "https://www.reddit.com/user/acmeai_team", "https://news.example/2026/10/acme-raises-money",
            "https://x.com/acme_other", "https://acme.example/")))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        self.assertEqual(self.run_row(run["id"])["status"], "running")      # it may go on
        self.advance(run["id"], self.tools())
        row = self.run_row(run["id"])
        self.assertIn("web", row["steps"])
        self.assertEqual((row["stats"]["web"]["by"], row["stats"]["web"]["queries"], row["stats"]["web"]["found"]),
                         ("worker", 2, 2))
        acc = self.accounts(run["id"])
        team = acc["reddit.com/user/acmeai_team"]
        self.assertTrue(team["how"].startswith("web search"))
        self.assertEqual((team["same"], team["rule"]), ("yes", "its profile names the other (links it as its own)"))
        self.assertEqual(team["found_why"], "the result names the widget model")
        other = acc["x.com/acme_other"]
        self.assertEqual(other["same"], "pending")                           # asked, never yes by its name
        self.assertFalse(any("news.example" in k for k in acc))             # an article is no identity
        self.assertEqual(acc["acme.example"]["how"].startswith("web search"), False)   # the confirmed one untouched
        self.answer_pairs(lambda b: "no" if b == "x.com/acme_other" else "yes")
        view = self.view(run["id"])
        self.assertIn("x.com/acme_other", {a["key"] for a in view["maker"]["not_same"]})
        self.assertIn("reddit.com/user/acmeai_team", {a["key"] for a in view["maker"]["accounts"]})
        self.assertEqual(view["run"]["web_search"], {"by": "worker", "waiting": False,
                                                     "asked": ['"acmeai"', '"acmeai" site:reddit.com']})

    def test_the_same_question_is_one_task_and_its_answer_reused(self):
        first = self.start(self.SEED)
        self.advance(first["id"], self.tools())
        task = self.web_task(first["id"])
        self.answer((task["id"], websearch_answer("https://www.reddit.com/user/acmeai_team")))
        second = self.start(self.SEED)
        self.advance(second["id"], self.tools())
        self.assertEqual(self.web_task(second["id"])["id"], task["id"])
        row = self.run_row(second["id"])
        self.assertIn("web", row["steps"])                                    # answered already: no wait
        self.assertEqual(row["search_calls"], 0)                              # and nothing spent on it
        self.assertEqual(self.accounts(second["id"])["reddit.com/user/acmeai_team"]["same"], "yes")

    def test_the_cap_a_run_with_its_searches_spent_asks_less_or_nothing(self):
        run = self.start(self.SEED)
        with self.conn.transaction():
            self.cur.execute("UPDATE mx_research_runs SET search_calls = %s WHERE id = %s",
                             (research.WEB_QUERIES + research.DISCUSSION_SEARCHES - 2, run["id"]))
        self.advance(run["id"], self.tools())
        task = self.web_task(run["id"])
        self.assertIn("Searches allowed: at most 2", task["input"])
        self.assertEqual(self.run_row(run["id"])["search_calls"], research.WEB_QUERIES + research.DISCUSSION_SEARCHES)
        spent = self.start(self.SEED + "?again")
        with self.conn.transaction():
            self.cur.execute("UPDATE mx_research_runs SET search_calls = %s WHERE id = %s",
                             (research.WEB_QUERIES + research.DISCUSSION_SEARCHES, spent["id"]))
        self.advance(spent["id"], self.tools())
        self.assertIsNone(self.web_task(spent["id"]))
        row = self.run_row(spent["id"])
        self.assertEqual(row["stats"]["web"]["why"], "the run's searches are spent")
        self.assertEqual(row["search_calls"], research.WEB_QUERIES + research.DISCUSSION_SEARCHES)

    def test_a_failed_question_is_said_and_the_run_goes_on(self):
        run = self.start(self.SEED)
        self.advance(run["id"], self.tools())
        task = self.web_task(run["id"])
        for _ in range(3):
            self.answer((task["id"], {"candidates": "none", "queries": []}))
        self.assertEqual(self.row(task["id"])["status"], "failed")
        self.advance(run["id"], self.tools())
        row = self.run_row(run["id"])
        self.assertEqual(row["stats"]["web"]["failed"], "failed")
        self.assertTrue(any("web search gave no valid answer" in (u.get("why") or "") for u in self.view(run["id"])["unread"]))

    def test_searxng_or_brave_configured_never_asks_the_worker(self):
        class Search:
            name = "stub"

            async def search(self, http, q):
                return []
        run = self.start(self.SEED)
        self.advance(run["id"], self.tools(search=Search()))
        self.assertIsNone(self.web_task(run["id"]))
        self.assertIn("web", self.run_row(run["id"])["steps"])
        off = self.start(self.SEED)
        self.advance(off["id"], self.tools(search=None))                    # INSIGHT_WEB_SEARCH=off
        self.assertEqual(self.run_row(off["id"])["stats"]["web"], {"off": "no web search is configured"})
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'websearch'")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_the_settings_say_the_worker_by_default(self):
        with mock.patch.dict("os.environ", {W.WEB_SEARCH_ENV: "", W.WEB_SEARCH_URL_ENV: "", W.WEB_SEARCH_KEY_ENV: ""}):
            status, body = call("GET", "/api/markx/research/settings")
        self.assertEqual((status, body["web_search"]), (200, "worker"), body)


if __name__ == "__main__":
    unittest.main()
