"""Which rules made a piece of derived data (issue 0071): its stamp, derived from the rules
themselves, never bumped by hand.

A stamp is a fingerprint of what the rules make of a fixed sample, kept here: made-up sources,
posts, addresses and bodies, written to exercise every rule (tests/test_stamps.py checks they still
do), each tuned value with a case at its edge (in at the value, out just past it). A rule change that changes the output on the sample changes the stamp, so the next start makes
the data again: the stories regroup in full (StoriesService), Discover's addresses refill
(discover_rules), the stored bodies are repaired again (PostsService). A change with the same output
(a rename, a move, a comment) keeps the stamp, and nothing is redone. Search's vectors are stamped
the same way in SQL (search_vector_version(), migration 0055).

Measured (issue 0071 B1): replaying the two changes that were missed by hand, 0068's site_of (one
site per github.io writer) and 0068's titles of outside origins, each changes its stamp; splitting
the rule files (0071 C2) keeps both. A hash of the rules' code catches both too, but changes with
every refactor, so each would regroup everything.

What the sample doesn't show, its stamp can't see: a new rule adds its case here (adding a case
changes the stamp, so the data is made again once).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


def fingerprint(value: Any) -> str:
    """A short hash of `value` (dataclasses, sets and datetimes included), the same for equal values."""
    def plain(v: Any) -> Any:
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            return dataclasses.asdict(v)
        if isinstance(v, (set, frozenset)):
            return sorted(v, key=repr)
        if isinstance(v, datetime):
            return v.isoformat()
        raise TypeError(f"no fingerprint for {type(v).__name__}")
    text = json.dumps(value, default=plain, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


# ---- addresses: Discover's (discover_rules.discover_address, discover_article) --------------------

ADDRESSES = (
    # a tweet on any host is its author's; an id too short is no tweet
    "https://x.com/writer_x/status/1900000000000000101",
    "https://nitter.local/writer_x/status/1900000000000000101",
    "https://xcancel.com/i/status/1900000000000000999",
    "https://x.com/writer_x/status/123",
    "https://x.com/writer_x",
    "https://x.com/search?q=sample",
    # platform accounts and the kinds of page that name none
    "https://t.me/sample_channel/101",
    "https://t.me/sample_channel",
    "https://t.me/s/sample_channel",
    "https://reddit.com/r/samplesub/comments/abc123/sample_model_weights",
    "https://reddit.com/u/sample_user",
    "https://youtube.com/watch?v=abcdefghijk",
    "https://youtube.com/channel/UCabc123",
    "https://youtube.com/@samplechannel/videos",
    "https://github.com/sample-org/sample-repo/releases/tag/v1.2.0",
    "https://medium.com/@writer/a-long-title-about-models-and-data",
    # a hosting platform's subdomain is its own site (issue 0068); a co.uk-like ending keeps three labels
    "https://writer-one.github.io/2026/03/routing",
    "https://deep.writer-one.github.io/notes/on-sample-data",
    "https://writer.bearblog.dev/notes-on-small-models",
    "https://space-name.hf.space/",
    "https://site.app.on-acorn.io/run",
    "https://sample.blogspot.com/2026/03/a-post.html",
    "https://news.sample.co.uk/tech/2026/03/story",
    # websites: articles by a date or a slug of 4+ words; the rest
    "https://launch.example/news/lab-model-seven-released",
    "https://launch.example/pricing",
    "https://beta.example/2026/03/short",
    "https://delta.example/blog/post",
    "http://insecure.example/a-plain-old-page-with-many-words",
    "https://linkedin.com/in/someone",
)


# ---- sources and posts: the story job's (StoriesService._story_post, story_rules, news_rules) ----

FOLLOWED = datetime(2025, 12, 1, 8, 0, tzinfo=timezone.utc)
T0 = datetime(2026, 3, 2, 9, 30, tzinfo=timezone.utc)

# (id, platform, handle_or_url, name, created_at): as SourceFacts and NewsRepository.followed_since read them
SOURCES: Tuple[Tuple[str, str, str, str, datetime], ...] = (
    ("s-alpha", "rss", "https://blog.alpha.example/feed", "Alpha Blog", FOLLOWED),
    ("s-beta", "rss", "https://www.beta.example/rss", "Beta News", FOLLOWED),
    ("s-one", "rss", "https://writer-one.github.io/feed.xml", "Writer One", FOLLOWED),
    ("s-two", "rss", "https://writer-two.github.io/atom.xml", "Writer Two", FOLLOWED),
    ("s-gamma", "rss", "https://gamma.example/research", "Gamma Research", FOLLOWED),
    ("s-tg1", "telegram", "https://tg.bridge.example/rss/sample_channel", "Sample Channel", FOLLOWED),
    ("s-tg2", "telegram", "https://tg.bridge.example/rss/other_channel", "Other Channel", FOLLOWED),
    ("s-x1", "rss", "https://nitter.local/writer_x/rss", "Writer X", FOLLOWED),
    ("s-x2", "rss", "https://nitter.local/author_y/rss", "Author Y", FOLLOWED),
    ("s-x3", "rss", "https://nitter.local/fan_z/rss", "Fan Z", FOLLOWED),
    ("s-red", "reddit", "https://www.reddit.com/r/samplesub/.rss", "r/samplesub", FOLLOWED),
    ("s-hn", "rss", "https://hnrss.org/frontpage", "Hacker News", FOLLOWED),
    ("s-saved", "saved", "saved", "Saved", FOLLOWED),
    ("s-new", "rss", "https://delta.example/feed", "Delta", T0 - timedelta(days=1)),
    ("s-press", "rss", "https://feeds.example/press", "Press Room", FOLLOWED),
)
# (source id, host, posts): where each source's posts are
HOSTS: Tuple[Tuple[str, str, int], ...] = (
    ("s-alpha", "blog.alpha.example", 12), ("s-beta", "beta.example", 9), ("s-one", "writer-one.github.io", 6),
    ("s-two", "writer-two.github.io", 4), ("s-two", "writer-one.github.io", 1), ("s-gamma", "gamma.example", 5),
    ("s-tg1", "t.me", 20), ("s-tg2", "t.me", 15), ("s-x1", "x.com", 10), ("s-x2", "x.com", 7), ("s-x3", "x.com", 3),
    ("s-red", "reddit.com", 8), ("s-hn", "db.example", 1), ("s-hn", "blog.alpha.example", 1),
    ("s-hn", "writer-one.github.io", 1), ("s-saved", "saved.example", 1), ("s-new", "delta.example", 3),
    ("s-press", "press.example", 2), ("s-press", "mirror-a.example", 1), ("s-press", "mirror-b.example", 1),
)

L1 = "https://launch.example/news/lab-model-seven-released"
L1_CARD = "https://launch.example/blog/lab-model-seven-card"
L2 = "https://paper.example/research/sparse-routing-at-scale"
L3 = "https://news.example/2026/03/open-weights-arrive-for-everyone"
L4 = "https://tool.example/blog/fast-tokenizer-ships"
L5 = "https://db.example/projects/tiny"
L6 = "https://notes.example/p/ab12"
L7 = "https://misc.example/a/b1"
L8 = "https://ref.example/guides/alpha-migration-guide"
L9 = "https://bench.example/papers/long-context-retrieval-benchmarks"
L10 = "https://edge.example/notes/three-days-apart"
SAME_PLACE = "https://beta.example/one-address-a-month-apart"
PRESS = "https://press.example/2026/03/press-release-on-models"
TWEET = "https://x.com/writer_x/status/1900000000000000101"
GUEST = "https://writer-one.github.io/guest-post-on-indexes"
SAVED = "https://saved.example/essays/on-careful-measurement"
TOOL_PREVIEW = (f'<p>Worth a look</p><blockquote cite="{L4}"><cite><b>Tool Site</b></cite></br>'
                '<b>Fast Tokenizer Ships</b></br>Tokenizing is now faster.</blockquote>')
QUOTE = (f'<p>Great thread</p><blockquote><b>Writer X</b>Thread on evaluation methods<footer> — <cite>'
         f'<a href="{TWEET}">x.com/writer_x</a></cite></footer></blockquote>')


def _reddit(user: str) -> str:
    return f'<p>submitted by <a href="https://www.reddit.com/user/{user}"> /u/{user} </a></p>'


def _post(pid: str, source: str, at: datetime, title: Optional[str], url: Optional[str], *,
          links: Sequence[Tuple[str, Optional[str]]] = (), texts: Optional[Dict[str, str]] = None,
          html: Optional[str] = None, content_hash: Optional[str] = None, chars: int = 0, author: Optional[str] = None,
          reposted_by: Sequence[str] = (), updated: bool = False, stored: Optional[datetime] = None) -> Dict[str, Any]:
    """A post as load_posts returns it, stored an hour after it was posted unless `stored` says when."""
    return {"id": pid, "source_id": source, "t": at, "title": title, "content_hash": content_hash or "h-" + pid,
            "text_chars": chars or 400, "url": url, "html": html, "updated": updated, "author": author,
            "reposted_by": list(reposted_by), "links": list(links), "link_texts": dict(texts or {}),
            "stored_at": stored or at + timedelta(hours=1)}


def _at(hours: float, minutes: int = 0) -> datetime:
    return T0 + timedelta(hours=hours, minutes=minutes)


def _words(n: int) -> str:
    return "<p>" + " ".join(["word"] * n) + "</p>"


def posts() -> List[Dict[str, Any]]:
    """The sample's posts, as StoriesRepository.load_posts returns them (HTML only for PLATFORM_KINDS)."""
    p = _post
    return [
        # An outside page 2+ voices link within 72 hours (link), titled by the link words they agree
        # on; a fourth link 80 hours on is too late; a roundup's first link joins it, and a Reddit post
        # whose first link joins nothing is a member by its two other links (issue 0070). A name
        # surges in their titles (News), and joins a tweet with no link.
        p("a1", "s-alpha", _at(0), "Lab Model Seven arrives with a longer context", "https://blog.alpha.example/2026/03/lab-model-seven-arrives",
          links=[(L1, None), (L1_CARD, None)], texts={L1: "Lab Model Seven Released Today"}),
        p("a2", "s-beta", _at(3), "Lab Model Seven: what changed for developers", "https://beta.example/lab-model-seven-developers",
          links=[(L1, None)], texts={L1: "Lab Model Seven Released Today"}),
        p("a3", "s-tg1", _at(5), "Lab Model Seven вышла сегодня", "https://t.me/sample_channel/101", links=[(L1, None)],
          texts={L1: "релиз"}, html="<p>Lab Model Seven вышла сегодня</p>"),
        p("a4", "s-tg2", _at(72, 1), "Lab Model Seven notes", "https://t.me/other_channel/202", links=[(L1, None)], html="<p>notes</p>"),
        p("a5", "s-red", _at(6), "Lab Model Seven weights", "https://reddit.com/r/samplesub/comments/abc123/lab_model_seven_weights",
          links=[("https://files.example/models/lab-model-seven-gguf", None), (L1, None), (L1_CARD, None)], html=_reddit("sample_user")),
        p("a6", "s-x1", _at(10), "Lab Model Seven is fast", "https://x.com/writer_x/status/1900000000000000001",
          author="writer_x", html="<p>Lab Model Seven is fast</p>"),
        p("o1", "s-beta", _at(8), "This week in models", "https://beta.example/this-week-in-models",
          links=[(L1, None), (L2, None), (L4, None)]),
        # Link words a slug confirms
        p("b1", "s-gamma", _at(24), "Sparse routing at scale", "https://gamma.example/research/sparse-routing-notes",
          links=[(L2, None)], texts={L2: "sparse routing at scale"}),
        p("b2", "s-one", _at(26), "Reading the routing paper", "https://writer-one.github.io/2026/03/routing",
          links=[(L2, None)], texts={L2: "this paper"}),
        # A slug made readable; a watched page updated since its date has no trusted time
        p("c1", "s-two", _at(30), "Open weights, finally", "https://writer-two.github.io/open-weights", links=[(L3, None)]),
        p("c2", "s-beta", _at(30, 5), "Weights are open", "https://beta.example/open-weights-arrive", links=[(L3, None)], updated=True),
        # The page's own words, as a link preview quotes them
        p("d1", "s-tg1", _at(40), "Worth a look", "https://t.me/sample_channel/110", links=[(L4, None)], html=TOOL_PREVIEW),
        p("d2", "s-alpha", _at(41), "Links for the week of tokens", "https://blog.alpha.example/2026/03/tokenizer-links",
          links=[(L4, None)], texts={L4: "a tokenizer"}),
        # A link post that is only this link titles it
        p("e1", "s-hn", _at(50), "Show HN: A tiny database in one file", L5, links=[(L5, None)], html="<p>Comments</p>"),
        p("e2", "s-tg2", _at(51), "Tiny db", "https://t.me/other_channel/210", links=[(L5, None)], html="<p>Tiny db</p>"),
        # One voice's link words that read as a title; no title at all
        p("f1", "s-alpha", _at(60), "On caching", "https://blog.alpha.example/2026/03/caching", links=[(L6, None)],
          texts={L6: "A Short Note On Caching"}),
        p("f2", "s-tg1", _at(61), "кэш", "https://t.me/sample_channel/120", links=[(L6, None)], html="<p>кэш</p>"),
        p("g1", "s-beta", _at(70), "Misc one", "https://beta.example/misc-one", links=[(L7, None)]),
        p("g2", "s-tg2", _at(70, 20), "Misc two", "https://t.me/other_channel/220", links=[(L7, None)], html="<p>two</p>"),
        # A page at its own site and Hacker News' post of it (address); a citation; a page that is no
        # origin leaves its posts to time: 10+ minutes after the origin (time), or less (none).
        p("h1", "s-alpha", _at(80), "Alpha update for March", "https://blog.alpha.example/2026/03/alpha-update"),
        p("h2", "s-hn", _at(81), "Alpha update for March", "https://blog.alpha.example/2026/03/alpha-update", html="<p>c</p>"),
        p("h3", "s-tg1", _at(82), "Апдейт", "https://t.me/sample_channel/130",
          links=[("https://blog.alpha.example/2026/03/alpha-update", "h1"), (L8, None)], html="<p>a</p>"),
        p("h4", "s-tg2", _at(80, 10), "Guide", "https://t.me/other_channel/230", links=[(L8, None)], html="<p>g</p>"),
        p("h5", "s-x3", _at(83), "The update is good", "https://x.com/fan_z/status/1900000000000000140",
          links=[("https://blog.alpha.example/2026/03/alpha-update", "h1")], author="fan_z", html="<p>update</p>"),
        p("h6", "s-x1", _at(80, 11), "The migration guide is good", "https://x.com/writer_x/status/1900000000000000060",
          links=[(L8, None)], author="writer_x", html="<p>guide</p>"),
        # A date alone counts as that day's earliest timed post of its story, never 00:00 (issue 0072 D)
        p("h7", "s-gamma", datetime(2026, 3, 5, tzinfo=timezone.utc), "Notes on the March update",
          "https://gamma.example/research/notes-on-the-march-update",
          links=[("https://blog.alpha.example/2026/03/alpha-update", "h1")]),
        # On X: a thread, a repost held by another source (its author a voice), a quote, a reposter
        p("t1", "s-x1", _at(90), "Thread on evaluation methods, part one of the series", TWEET, author="writer_x",
          reposted_by=["fan_z"], html="<p>Thread on evaluation methods</p>"),
        p("t2", "s-x1", _at(90, 2), "R to @writer_x: part two, with the numbers", "https://x.com/writer_x/status/1900000000000000102",
          author="writer_x", html="<p>part two</p>"),
        p("t3", "s-x2", _at(91), "RT by @author_y: Thread on evaluation methods, part one of the series", TWEET,
          author="writer_x", html="<p>Thread on evaluation methods</p>"),
        p("t4", "s-x3", _at(92), "Great thread", "https://x.com/fan_z/status/1900000000000000150",
          links=[(TWEET, "t1")], author="fan_z", html=QUOTE),
        # The same text (120+ characters) twice; a shorter one is no join; a time of day missing
        p("j1", "s-tg1", _at(100), "Новость дня: открыт исходный код", "https://t.me/sample_channel/140",
          content_hash="h-same-text", chars=120, html="<p>j1</p>"),
        p("j2", "s-tg2", _at(102), "Переслано", "https://t.me/other_channel/240", content_hash="h-same-text", chars=120, html="<p>j2</p>"),
        p("j5", "s-alpha", datetime(2026, 3, 7, tzinfo=timezone.utc), "Daily digest", "https://blog.alpha.example/digest",
          content_hash="h-same-text", chars=120),
        p("j6", "s-beta", datetime(2026, 4, 6, tzinfo=timezone.utc), "Digest again", "https://beta.example/digest-again",
          content_hash="h-same-text", chars=120),
        p("j7", "s-gamma", datetime(2026, 5, 6, 0, 1, tzinfo=timezone.utc), "Digest once more", "https://gamma.example/research/digest",
          content_hash="h-same-text", chars=120),
        p("j3", "s-tg1", _at(104), "Short one", "https://t.me/sample_channel/150", content_hash="h-short", chars=119, html="<p>s</p>"),
        p("j4", "s-tg2", _at(104, 30), "Short two", "https://t.me/other_channel/250", content_hash="h-short", chars=119, html="<p>s</p>"),
        # The same title of 5+ words, styled letters as plain (NFKC), within 7 days; not 8 days on. The
        # first was stored after the second (a late fetch): the story keeps the second's id (issue 0072 A).
        p("k1", "s-beta", _at(110), "A Field Guide To Small Language Models", "https://beta.example/field-guide",
          stored=_at(114)),
        p("k2", "s-gamma", _at(112), "𝐀 𝐅𝐢𝐞𝐥𝐝 𝐆𝐮𝐢𝐝𝐞 𝐓𝐨 𝐒𝐦𝐚𝐥𝐥 𝐋𝐚𝐧𝐠𝐮𝐚𝐠𝐞 𝐌𝐨𝐝𝐞𝐥𝐬", "https://gamma.example/research/field-guide"),
        p("k3", "s-alpha", _at(112 + 7 * 24), "A Field Guide To Small Language Models", "https://blog.alpha.example/field-guide"),
        p("k4", "s-tg1", _at(112 + 14 * 24, 1), "A Field Guide To Small Language Models", "https://t.me/sample_channel/160",
          html="<p>k4</p>"),
        # ... its entities decoded and its quotes as they are compared (utils/titles.py, issue 0071)
        p("k5", "s-tg2", _at(118), "Notes on &quot;Small&quot; Language Models Today", "https://t.me/other_channel/270",
          html="<p>k5</p>"),
        p("k6", "s-gamma", _at(119), "Notes on “Small” Language Models Today", "https://gamma.example/research/notes-on-small"),
        # Another path of a stored page is that page; a writer's guest post on another github.io site
        # is not at its own site (issue 0068), so Hacker News' post of it hangs from it by time
        p("m1", "s-gamma", _at(120), "Redesigning the index", "https://gamma.example/research/redesigning-the-index", updated=True),
        p("m2", "s-one", _at(121), "Notes on the index redesign", "https://writer-one.github.io/2026/03/index-notes",
          links=[("https://gamma.example/engineering/redesigning-the-index", None)]),
        p("m3", "s-two", _at(122), "A guest post on indexes", GUEST, links=[("https://gamma.example/research/redesigning-the-index", "m1")]),
        p("m4", "s-hn", _at(123), "A guest post on indexes", GUEST, html="<p>c</p>"),
        # A page you saved, two voices citing it: the page everyone links is the origin, no voice
        p("n1", "s-saved", _at(130), "On Careful Measurement", SAVED),
        p("n2", "s-beta", _at(131), "Why measurement matters", "https://beta.example/why-measure", links=[(SAVED, "n1")]),
        p("n3", "s-tg2", _at(132), "мерить", "https://t.me/other_channel/260", links=[(SAVED, "n1")], html="<p>m</p>"),
        # Two people in one subreddit are one place, two voices; a site linking it too makes the story
        p("r1", "s-red", _at(140), "A paper on long context retrieval", "https://reddit.com/r/samplesub/comments/r1/paper",
          links=[(L9, None)], html=_reddit("sample_user") + _words(56)),
        p("r2", "s-red", _at(141), "Long context retrieval, again", "https://reddit.com/r/samplesub/comments/r2/again",
          links=[(L9, None)], html=_reddit("other_user") + _words(57)),
        p("r3", "s-alpha", _at(142), "Retrieval benchmarks", "https://blog.alpha.example/2026/03/retrieval", links=[(L9, None)]),
        # A source followed for a day: its posts never start a name's surge
        p("w1", "s-new", _at(150), "Delta Engine Two", "https://delta.example/blog/engine-two"),
        # Edges: a link 72 hours on still joins; a reply 24 hours on continues its thread, a minute
        # more doesn't; one address 30 days apart; a source half of whose posts are on its site
        p("u1", "s-gamma", _at(160), "Three days", "https://gamma.example/research/three-days", links=[(L10, None)]),
        p("u2", "s-one", _at(232), "Three days on", "https://writer-one.github.io/2026/03/three-days-on", links=[(L10, None)]),
        p("t5", "s-x1", _at(114, 2), "R to @writer_x: part three, a day later", "https://x.com/writer_x/status/1900000000000000103",
          author="writer_x", html="<p>part three</p>"),
        p("t6", "s-x1", _at(138, 3), "R to @writer_x: part four, a day and a minute later",
          "https://x.com/writer_x/status/1900000000000000104", author="writer_x", html="<p>part four</p>"),
        p("v1", "s-beta", _at(170), "One address", SAME_PLACE),
        p("v2", "s-hn", _at(170 + 30 * 24), "One address, a month on", SAME_PLACE, html="<p>c</p>"),
        p("v3", "s-red", _at(170 + 60 * 24, 1), "One address, too late", SAME_PLACE, html=_reddit("sample_user")),
        p("x1", "s-press", _at(180), "A press release on models", PRESS),
        p("x2", "s-hn", _at(181), "Press release on models", PRESS, html="<p>c</p>"),
        # Names: 3 posts of 2 voices within 48 hours, said once in the 30 days before (and once
        # earlier) by another voice, surge; said twice in those days by others, 2 new voices don't
        p("y0", "s-tg2", _at(200 - 31 * 24), "Vector Index Nine preview", "https://t.me/other_channel/300", html="<p>y0</p>"),
        p("y1", "s-tg1", _at(200 - 29 * 24), "Vector Index Nine rumours", "https://t.me/sample_channel/300", html="<p>y1</p>"),
        p("y2", "s-alpha", _at(200), "Vector Index Nine is out", "https://blog.alpha.example/2026/03/vector-index-nine"),
        p("y3", "s-beta", _at(201), "Hands on with Vector Index Nine", "https://beta.example/vector-index-nine"),
        p("y4", "s-alpha", _at(248), "Vector Index Nine, two days in", "https://blog.alpha.example/2026/03/two-days-in"),
        # ... and a later wave of 3 voices new to it, more than said it before, surges again
        p("y5", "s-gamma", _at(300), "Vector Index Nine at work", "https://gamma.example/research/vector-index-nine"),
        p("y6", "s-one", _at(301), "Trying Vector Index Nine", "https://writer-one.github.io/2026/03/vector-index-nine"),
        p("y7", "s-two", _at(302), "Vector Index Nine notes", "https://writer-two.github.io/vector-index-nine"),
        p("z1", "s-tg1", _at(200 - 29 * 24), "Graph Engine Four leak", "https://t.me/sample_channel/310", html="<p>z1</p>"),
        p("z2", "s-tg2", _at(200 - 20 * 24), "Graph Engine Four again", "https://t.me/other_channel/310", html="<p>z2</p>"),
        p("z3", "s-alpha", _at(210), "Graph Engine Four ships", "https://blog.alpha.example/2026/03/graph-engine-four"),
        p("z4", "s-beta", _at(211), "Graph Engine Four, reviewed", "https://beta.example/graph-engine-four"),
        p("z5", "s-alpha", _at(212), "Graph Engine Four benchmarks", "https://blog.alpha.example/2026/03/graph-benchmarks"),
    ]


# ---- stored bodies: the repair of 0068 (parsing._without_hidden_link_labels) ----------------------

BODIES = (
    '<p>See <a href="https://a.example/post">the guide<span class="sr-only"> (opens in a new window)</span></a>.</p>',
    '<p>Read <a href="https://a.example/more">more<span class="visually-hidden">about the guide</span></a></p>',
    '<p><a href="https://a.example/x"><span class="screen-reader-text">Download</span></a></p>',
    '<p>A <span hidden>hidden note</span> outside a link, and <a href="https://a.example/y">a link</a>.</p>',
    '<p>Nothing to hide <a href="https://a.example/z">here</a>.</p>',
)
