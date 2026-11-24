"""Mark X's answer checks (0086 C): the shape and sets from each kind's schema, and what only the input can tell (spans
and versions in the post, figures in the members, cited keys, a translation's numbers and length). No database;
synthetic fixtures only."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.markx import schemas
from insight_core.markx.validate import check, figures, fold, missing_figures, version_occurs

POST = """Platform: telegram | Source: Example Channel
Title: Acme выпустила Widget‑4.1 Pro
Text: Acme released Widget-4.1 Pro today: 27B parameters, $500bn valuation, 1 000 users in ёлка mode.
Links, in order:
1. https://example.com/widget "Widget 4.1 launch notes\""""


def reading(**over):
    r = {"kind": "report", "events": "one",
         "main": {"headline_en": "Acme released Widget 4.1 Pro", "actors": ["Acme"], "object": "Widget 4.1 Pro",
                  "action": "released", "numbers": ["27B"]},
         "items": [], "mentions": [{"name": "Globex", "role": "background"}], "lang": "ru"}
    r.update(over)
    return r


def entity(**over):
    e = {"span": "Widget-4.1 Pro", "name": "Widget 4.1 Pro", "type": "product", "role": "subject", "maker": "Acme",
         "family": "Widget", "version": "4.1", "variant": "Pro", "size": None, "build": None}
    e.update(over)
    return e


def judge(**over):
    j = {"relation": "same_event", "confidence": 80, "reason": "Both report the launch."}
    j.update(over)
    return j


MEMBERS = """MEMBERS:
- id 0a1b2c3d [Example Site, site, 2026-11-02T10:00] Acme ships Widget 4.1 Pro | 27B parameters, priced at $20 | reading: report, Acme released Widget 4.1 Pro
- id 9f8e7d6c [Example Channel, telegram, 2026-11-02T12:00] Widget 4.1 Pro is out | Acme's new Widget | reading: report, Acme released Widget 4.1 Pro"""

DAY = """DAY 2026-11-02: 3 stories

[s1] Acme released Widget 4.1 Pro — 3 sources: Example Site, Example Channel
  - [Example Site, site, 10:00] Acme ships Widget 4.1 Pro — 27B parameters, priced at $20

[s2] Globex raised $300m — 2 sources: Example Blog
  - [Example Blog, site, 11:00] Globex raises $300m — a round led by Initech

[s3] Initech opened a lab — 2 sources: Example Forum
  - [Example Forum, hn, 12:00] Initech opens a lab in Lisbon — 40 researchers"""


def briefing(*lines):
    return {"lines": [{"text": t, "stories": s} for t, s in lines]}


class TheSchemaAndSets(unittest.TestCase):
    def test_a_valid_reading_passes(self):
        answer, error = check("read", reading(), POST)
        self.assertIsNone(error)
        self.assertEqual(answer["kind"], "report")

    def test_a_reading_under_its_own_key_is_unwrapped(self):
        answer, error = check("read", {"reading": reading()}, POST)
        self.assertIsNone(error)
        self.assertEqual(answer["events"], "one")

    def test_kind_events_and_lang_come_from_their_sets(self):
        self.assertIn("kind", check("read", reading(kind="news"), POST)[1])
        self.assertIn("events", check("read", reading(events="two"), POST)[1])
        self.assertIn("lang", check("read", reading(lang="Russian"), POST)[1])
        self.assertIn("role", check("read", reading(mentions=[{"name": "X", "role": "aside"}]), POST)[1])

    def test_main_is_null_exactly_when_events_is_none(self):
        self.assertIsNone(check("read", reading(events="none", main=None, kind="other"), POST)[1])
        self.assertIn("main must be null", check("read", reading(events="none"), POST)[1])
        self.assertIn("main is null", check("read", reading(main=None), POST)[1])

    def test_a_reading_headline_has_at_most_25_words(self):
        long = reading()
        long["main"] = dict(long["main"], headline_en=" ".join(["word"] * 26))
        self.assertIn("26 words", check("read", long, POST)[1])
        ok = reading()
        ok["main"] = dict(ok["main"], headline_en=" ".join(["word"] * 25))
        self.assertIsNone(check("read", ok, POST)[1])

    def test_a_missing_field_is_named(self):
        r = reading()
        del r["lang"]
        self.assertEqual(check("read", r, POST)[1], "answer: lang missing")

    def test_not_an_object_and_an_unknown_kind(self):
        self.assertEqual(check("read", ["x"], POST)[1], "answer: not an object")
        self.assertIn("unknown task kind", check("summarise", {}, POST)[1])

    def test_every_judge_kind_takes_a_relation_from_its_set_and_a_confidence_in_0_100(self):
        for kind in ("check", "join", "pair", "merge", "connect"):
            g = "judge-read-v1" if kind in ("join", "pair") else None   # v2 also quotes (JudgeQuotes0258)
            with self.subTest(kind=kind):
                self.assertIsNone(check(kind, judge(), "STORY ...", g)[1])
                self.assertIn("relation", check(kind, judge(relation="related"), "x", g)[1])
                self.assertIn("above 100", check(kind, judge(confidence=120), "x", g)[1])
                self.assertIn("below 0", check(kind, judge(confidence=-1), "x", g)[1])
                self.assertIn("not number", check(kind, judge(confidence="high"), "x", g)[1])
                self.assertIn("confidence missing", check(kind, {"relation": "different"}, "x", g)[1])


class Entities(unittest.TestCase):
    def test_spans_and_versions_in_the_post_pass(self):
        answer, error = check("entities", {"entities": [entity(), entity(span="Acme", name="Acme", type="org",
                                                                         role="actor", maker=None, family=None,
                                                                         version=None, variant=None)],
                                           "relations": [{"a": "Acme", "rel": "released", "b": "Widget 4.1 Pro"}]}, POST)
        self.assertIsNone(error)
        self.assertEqual(len(answer["entities"]), 2)

    def test_a_span_not_in_the_post_is_refused(self):
        # the only entity dropped, so nothing is left: refused (asked again), saying why
        error = check("entities", {"entities": [entity(span="Widget 5 Pro")]}, POST)[1]
        self.assertEqual(error, "every entity was dropped: entities[0].span 'Widget 5 Pro' does not occur in the post")

    def test_spans_compare_folded_case_dashes_and_yo(self):
        # the post writes "Widget‑4.1" with a non-breaking hyphen, "ёлка" with ё, "выпустила" in lower case
        for span in ("widget-4.1 pro", "Widget–4.1 Pro", "елка", "ВЫПУСТИЛА"):
            with self.subTest(span=span):
                self.assertIsNone(check("entities", {"entities": [entity(span=span, version=None)]}, POST)[1])

    def test_a_version_not_in_the_post_is_refused(self):
        error = check("entities", {"entities": [entity(version="4.2")]}, POST)[1]
        self.assertEqual(error, "every entity was dropped: entities[0].version '4.2' does not occur in the post")
        self.assertTrue(version_occurs("4.1", POST))
        self.assertTrue(version_occurs("Widget 4.1", "the Widget-4.1 notes"))

    def test_the_folded_input_is_kept_and_each_input_read_as_its_own(self):
        # the input's folded forms are kept between one answer's checks; a different input is folded anew
        from insight_core.markx.validate import occurs
        texts = [f"post {n}: Widget-{n}.1 notes" for n in range(20)]
        for _ in range(2):
            for n, text in enumerate(texts):
                self.assertTrue(occurs(f"post {n}:", text))
                self.assertFalse(occurs(f"post {n + 1}:", text))
                self.assertTrue(version_occurs(f"{n}.1", text))
                self.assertFalse(version_occurs(f"{n + 1}.1", text))
        self.assertFalse(occurs("anything", None))

    def test_type_and_role_come_from_their_sets(self):
        self.assertIn("type", check("entities", {"entities": [entity(type="company")]}, POST)[1])
        self.assertIn("role", check("entities", {"entities": [entity(role="main")]}, POST)[1])
        # a relation outside the set is dropped (relations have no reader), the answer stands
        answer, error = check("entities", {"entities": [], "relations": [{"a": "A", "rel": "likes", "b": "B"}]}, POST)
        self.assertIsNone(error)
        self.assertEqual(answer["relations"], [])
        self.assertIn("rel", answer["dropped"][0]["why"])

    def test_at_most_twenty_entities(self):
        self.assertIsNone(check("entities", {"entities": [entity()] * 20}, POST)[1])
        # the first 20 stored (the guide puts subjects, actors and versions first), the 21st dropped
        answer, error = check("entities", {"entities": [entity()] * 20 + [entity(name="Gadget")]}, POST)
        self.assertIsNone(error)
        self.assertEqual(len(answer["entities"]), 20)
        self.assertEqual(answer["dropped"], [{"list": "entities", "item": entity(name="Gadget"),
                                              "why": "entities[20]: past entry 20"}])

    def test_no_entities_is_fine(self):
        self.assertIsNone(check("entities", {"entities": [], "relations": []}, POST)[1])


class Salvage(unittest.TestCase):
    """An entity list's bad entries are dropped (kept under "dropped" with why), the rest stored."""
    ACME = entity(span="Acme", name="Acme", type="org", role="actor", maker=None, family=None, version=None,
                  variant=None)

    def test_one_bad_entity_among_good_ones_is_dropped_the_answer_stored(self):
        bad = entity(span="Gizmo 9", name="Gizmo 9", role="mention", version=None)
        answer, error = check("entities", {"entities": [entity(), bad, self.ACME], "relations": []}, POST, "ent-v4.2")
        self.assertIsNone(error)
        self.assertEqual([e["name"] for e in answer["entities"]], ["Widget 4.1 Pro", "Acme"])
        self.assertEqual(answer["dropped"], [{"list": "entities", "item": bad,
                                              "why": "entities[1].span 'Gizmo 9' does not occur in the post"}])

    def test_each_kind_of_bad_entry_is_dropped(self):
        cases = {"version": entity(role="mention", version="4.2"),
                 "type": entity(role="mention", type="company"),
                 "recommended": entity(role="recommended"),
                 "span": dict(entity(role="mention"), span="")}
        for what, bad in cases.items():
            with self.subTest(what=what):
                answer, error = check("entities", {"entities": [entity(), bad]}, POST, "ent-v4.2")
                self.assertIsNone(error)
                self.assertEqual(len(answer["entities"]), 1)
                self.assertEqual(len(answer["dropped"]), 1)

    def test_an_answer_that_loses_every_subject_is_still_asked_again(self):
        error = check("entities", {"entities": [entity(span="Widget 5 Pro", version=None), self.ACME]}, POST)[1]
        self.assertEqual(error, "every subject was dropped: entities[0].span 'Widget 5 Pro' does not occur in the post")
        # another subject kept: stored
        answer, error = check("entities", {"entities": [entity(span="Widget 5 Pro", version=None),
                                                        dict(self.ACME, role="subject")]}, POST)
        self.assertIsNone(error)

    def test_salvage_is_idempotent_and_keeps_what_was_dropped_before(self):
        once, _ = check("entities", {"entities": [entity(), entity(span="Gizmo 9", role="mention", version=None)]}, POST)
        twice, error = check("entities", once, POST)
        self.assertIsNone(error)
        self.assertEqual(twice, once)

    def test_other_kinds_and_shapes_are_left_alone(self):
        from insight_core.markx.validate import salvage
        self.assertEqual(salvage("read", {"kind": "x"}, POST), {"kind": "x"})
        self.assertEqual(check("entities", {"entities": "bogus"}, POST)[1], "answer.entities: not array")
        self.assertIn("not object", check("entities", {"entities": ["x"]}, POST)[1])


class StoryAnswers(unittest.TestCase):
    def card(self, **over):
        c = {"headline_en": "Acme released Widget 4.1 Pro", "actors": ["Acme"], "object": "Widget 4.1 Pro",
             "action": "released", "date": "2026-11-02", "summary_en": "Acme released it. Two sources.",
             "kinds": {"report": 2}, "odd": []}
        c.update(over)
        return c

    def test_a_card_passes_with_its_slots(self):
        self.assertIsNone(check("card", self.card(), MEMBERS)[1])
        self.assertIsNone(check("card", {"card": self.card(odd=["9f8e7d6c"])}, MEMBERS)[1])

    def test_a_card_needs_its_slots_and_a_short_headline(self):
        c = self.card()
        del c["action"]
        self.assertEqual(check("card", c, MEMBERS)[1], "answer: action missing")
        self.assertIn("15 words", check("card", self.card(headline_en=" ".join(["w"] * 15)), MEMBERS)[1])

    def test_a_card_odd_member_must_be_a_member(self):
        self.assertEqual(check("card", self.card(odd=["deadbeef"]), MEMBERS)[1], "odd names 'deadbeef', not a member")

    def test_a_headline_with_figures_and_versions_from_the_members_passes(self):
        self.assertIsNone(check("headline", {"headline_en": "Acme ships Widget 4.1 Pro with 27B parameters at $20",
                                             "summary_en": "Acme released Widget 4.1 Pro."}, MEMBERS)[1])

    def test_a_headline_figure_or_version_no_member_has_is_refused(self):
        self.assertEqual(check("headline", {"headline_en": "Acme ships Widget 4.1 Pro at $25"}, MEMBERS)[1],
                         "headline_en: the figure 25 occurs in no member")
        self.assertEqual(check("headline", {"headline_en": "Acme ships Widget 4.2 Pro"}, MEMBERS)[1],
                         "headline_en: the version 'Widget 4.2' occurs in no member")
        self.assertIn("17 words", check("headline", {"headline_en": " ".join(["w"] * 17)}, MEMBERS)[1])

    def test_a_headline_has_two_words_of_slack_over_the_guides_14(self):
        """A card keeps its 14-word headline limit: its headline is the judge's, not the page's (0121)."""
        self.assertIsNone(check("headline", {"headline_en": " ".join(["w"] * 16)}, MEMBERS)[1])
        self.assertIn("more than 16", check("headline", {"headline_en": " ".join(["w"] * 17)}, MEMBERS)[1])
        self.assertIn("15 words", check("card", self.card(headline_en=" ".join(["w"] * 15)), MEMBERS)[1])

    def test_a_card_that_numbers_its_odd_members_is_kept_as_given(self):
        """Nothing reads `odd`, so odd members named by position are not refused."""
        self.assertIsNone(check("card", self.card(odd=[2]), MEMBERS)[1])

    def test_a_headline_version_is_found_by_its_number(self):
        """A headline's "GPT-5.6" where its members say "their 5.6 versions" is right, not invented."""
        members = MEMBERS + "\n- id 11111111 [Example Blog, site, 2026-11-02T13:00] Cheaper than their 5.6 versions | x"
        self.assertIsNone(check("headline", {"headline_en": "Acme prices Widget 4.1 Pro below Widget 5.6"}, members)[1])
        self.assertIn("'Widget 5.7'", check("headline", {"headline_en": "Acme prices it below Widget 5.7"}, members)[1])

    def test_a_reading_names_any_number_of_actors_and_says_what_is_wrong_inside_main(self):
        r = reading()
        r["main"] = dict(r["main"], actors=[f"Org {n}" for n in range(9)])
        self.assertIsNone(check("read", r, POST)[1])
        r["main"] = dict(r["main"], actors="Acme")
        self.assertEqual(check("read", r, POST)[1], "answer.main.actors: not array")

    def test_a_briefing_line_may_cite_the_days_own_date(self):
        ok = briefing(("Acme released Widget 4.1 Pro on 2 November 2026.", ["s1"]),
                      ("Globex raised $300m.", ["s2"]), ("Initech opened a lab.", ["s3"]))
        self.assertIsNone(check("briefing", ok, DAY)[1])

    def test_a_briefing_of_five_to_seven_lines_citing_the_days_stories(self):
        ok = briefing(("Acme released Widget 4.1 Pro, with 27B parameters.", ["s1"]),
                      ("Globex raised $300m.", ["s2"]), ("Initech opened a lab of 40 researchers.", ["s3"]))
        self.assertIsNone(check("briefing", ok, DAY)[1])   # three stories: three lines are enough

    def test_a_briefing_line_count_follows_the_day(self):
        one = briefing(("Acme released Widget 4.1 Pro.", ["s1"]))
        self.assertEqual(check("briefing", one, DAY)[1], "1 lines; the day has 3 stories, so 3 to 7")
        eight = briefing(*[("Acme released Widget 4.1 Pro.", ["s1"])] * 8)
        self.assertIn("more than 7", check("briefing", eight, DAY)[1])

    def test_a_briefing_line_cites_only_the_days_keys(self):
        bad = briefing(("Acme released Widget 4.1 Pro.", ["s1"]), ("Globex raised money.", ["s9"]),
                       ("Initech opened a lab.", ["s3"]))
        self.assertEqual(check("briefing", bad, DAY)[1], "lines[1] cites 's9', not a story of the day")

    def test_a_briefing_figure_must_be_in_a_cited_story_not_another(self):
        bad = briefing(("Acme released Widget 4.1 Pro after a $300m round.", ["s1"]),
                       ("Globex raised $300m.", ["s2"]), ("Initech opened a lab.", ["s3"]))
        self.assertEqual(check("briefing", bad, DAY)[1], "lines[0]: the figure 300 occurs in none of its stories (s1)")
        good = briefing(("Acme released Widget 4.1 Pro after a $300m round.", ["s1", "s2"]),
                        ("Globex raised $300m.", ["s2"]), ("Initech opened a lab.", ["s3"]))
        self.assertIsNone(check("briefing", good, DAY)[1])


class Translation(unittest.TestCase):
    SOURCE = "Title: Acme выпустила Widget 4.1\nText: Модель на 27B параметров стоит $20 в месяц, 1 000 пользователей."

    def test_a_translation_that_keeps_the_numbers_passes(self):
        self.assertIsNone(check("translate", {"title_en": "Acme released Widget 4.1",
                                              "text_en": "The 27B model costs $20 a month, 1,000 users."}, self.SOURCE)[1])

    def test_a_dropped_number_is_refused(self):
        self.assertEqual(check("translate", {"title_en": "Acme released Widget 4.1",
                                             "text_en": "The 27B model costs a little per month, many users."},
                               self.SOURCE)[1], "the number 20 of the post is not in the translation")

    def test_the_length_stays_within_half_and_twice(self):
        short = check("translate", {"title_en": "Widget 4.1", "text_en": "Costs $20, 27B, 1000"}, self.SOURCE)[1]
        self.assertIn("outside 0.5-2.0x", short)
        long = check("translate", {"title_en": "Acme released Widget 4.1",
                                   "text_en": "The 27B model costs $20 a month, 1,000 users. " * 5}, self.SOURCE)[1]
        self.assertIn("outside 0.5-2.0x", long)


class TheHelpers(unittest.TestCase):
    def test_figures_read_as_bare_digits(self):
        self.assertEqual(figures("$500bn, 1 000 users, 2,5%"), ["500", "1000", "25"])
        self.assertEqual(missing_figures("a $500bn deal", "valued at $500 billion"), [])
        self.assertEqual(missing_figures("in 2026", "the 2026-11-02 release"), [])

    def test_fold(self):
        self.assertEqual(fold("Ёлка  —  Widget‑4"), "елка - widget-4")

    def test_typographic_apostrophes_and_quotes_fold_as_plain_ones(self):
        """An apostrophe's form ("Where's" against the post's "Where’s") does not refuse a name (0121)."""
        self.assertEqual(fold("Where’s ‘it’ “now”"), fold("Where's 'it' \"now\""))
        post = POST.replace("Title: Acme выпустила Widget‑4.1 Pro", "Title: Acme’s “Widget‑4.1 Pro” is out")
        for span in ("Acme's", "Acme’s", '"Widget-4.1 Pro"', "“Widget-4.1 Pro”"):
            with self.subTest(span=span):
                self.assertIsNone(check("entities", {"entities": [entity(span=span, version=None)]}, post)[1])


class TheKindsAndGuides(unittest.TestCase):
    def test_twelve_kinds_each_with_a_guide_file_and_a_schema(self):
        self.assertEqual(set(schemas.KINDS), {"read", "entities", "check", "join", "pair", "card", "merge", "connect",
                                              "headline", "briefing", "translate", "embed",
                                              "alias", "collide", "embed_name",
                                              "alias2", "alias3", "alias4",
                                              "rename", "stop", "chain", "derive",
                                              "perspective", "sheet", "read3", "dispute",
                                              "relate", "stance",
                                              "back",
                                              "cite",
                                              "track", "subtopics", "probes",
                                              "digest", "subtopic_place",
                                              "scout", "identity",
                                              "websearch",
                                              "source_judge", "question",
                                              "news_sections", "discussion",
                                              "reading",
                                              "news_place",
                                              "unit_types",
                                              "significance",
                                              "track_schema", "track_things", "track_same"})
        for kind in schemas.KINDS.values():
            with self.subTest(kind=kind.name):
                self.assertTrue((schemas.GUIDES_DIR / f"{kind.guide}.md").is_file())
                self.assertIsInstance(kind.schema, dict)
                self.assertIn(kind.subject, ("post", "post_story", "post_post", "story", "story_story", "day",
                                             "entity", "entity_entity", "source", "track", "post_track",
                                             "research_pair", "research_run",
                                             "source_candidate", "question",
                                             "news_run",
                                             "thing_thing"))

    def test_the_guides_name_no_channel_account_or_subreddit(self):
        """No handle, channel or subreddit address in any guide (persp-v1's "@x" is a placeholder)."""
        for path in sorted(schemas.GUIDES_DIR.glob("*.md")):
            with self.subTest(guide=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"t\.me/|(?<![\w.])r/\w|(?<![\w.])@(?!handles\b|x\b)\w|x\.com/|twitter\.com/|youtube\.com/", text))


class JudgeQuotes0258(unittest.TestCase):
    """judge-read-v2 (join and pair): an answer quotes the POST it judged, so an answer written from another question's
    content is refused; a quote of the post's own words passes (0258)."""

    @staticmethod
    def question(kind="pair"):
        from datetime import datetime, timezone
        from insight_core.markx import tasks
        at = datetime(2100, 3, 1, tzinfo=timezone.utc)
        anchor = tasks.Post("a1", "x", "Example Dev News", "s1", at, "Cursor adds Fable 5.2",
                            "Cursor added Claude Fable 5.2, scoring 56.9% on CursorBench, available to every plan.")
        post = tasks.Post("p2", "telegram", "Example Physics", "s2", at, "Black holes and Fable 5.2",
                          "In 1983, physicists showed that black holes form very abruptly. Fable 5.2 found the "
                          "transition is abrupt there too.", links=[("https://example.com/paper", "the paper")])
        reading = {"kind": "commentary", "events": "one", "main": {"headline_en": "Model checks a physics result"},
                   "mentions": [{"name": "Fable 5.2", "role": "subject"}]}
        rd = {"a1": {"kind": "report", "main": {"headline_en": "Cursor adds Fable 5.2"}}, "p2": reading}
        if kind == "pair":
            return tasks.pair_input(anchor, post, rd)
        return tasks.join_input(post, reading, [anchor], {"headline_en": "Cursor adds Fable 5.2 with a CursorBench score",
                                                          "summary_en": "Cursor ships the model to every plan."})

    def test_the_kinds_ask_judge_read_v2_and_keep_v1(self):
        for kind in ("join", "pair"):
            self.assertEqual(schemas.KINDS[kind].guide, "judge-read-v2")
            self.assertEqual(schemas.answer_guides(kind), ("judge-read-v2", "judge-read-v1"))
            self.assertIn("post_quote", schemas.schema_for(kind, "judge-read-v2")["required"])
            self.assertIs(schemas.schema_for(kind, "judge-read-v1"), schemas.JUDGE_SCHEMA)
        self.assertEqual(schemas.guide_ids()["judge-read-v1"], "join")   # stored as before: its row loads unchanged
        self.assertEqual(schemas.guide_ids()["judge-read-v2"], "join")
        self.assertNotEqual(schemas.guide_body("judge-read-v1"), schemas.guide_body("judge-read-v2"))
        self.assertIn("post_quote", schemas.guide_body("judge-read-v2"))
        self.assertEqual(schemas.answer_guides("merge"), ("judge-story-v2", "judge-story-v1"))
        self.assertIs(schemas.schema_for("merge", "judge-story-v1"), schemas.JUDGE_SCHEMA)   # v1's answers kept
        self.assertEqual(schemas.guide_ids()["judge-story-v1"], "merge")
        v2 = schemas.guide_body("judge-story-v2")
        self.assertIn("One release is one row", v2)
        # the guide states the rule, never the measured cases' makers or models (0281 D)
        for name in ("Anthropic", "Fable", "Gemini", "Nvidia", "OpenAI", "Kimi", "DeepSeek", "Google"):
            self.assertNotIn(name, v2)

    def test_an_answer_written_from_another_question_is_refused(self):
        for kind in ("pair", "join"):
            text = self.question(kind)
            with self.subTest(kind=kind):
                cross = judge(post_quote="Cursor added Claude Fable 5.2, scoring 56.9% on CursorBench", confidence=90,
                              reason="Post announces Fable 5.2 availability in Cursor with its CursorBench score")
                # the story's words, though in this question, are not the POST's
                self.assertEqual(check(kind, cross, text, "judge-read-v2")[1],
                                 "post_quote: not in this question's POST title or text")
                elsewhere = judge(post_quote="the first physics problem of the story")
                self.assertIn("not in this question's POST", check(kind, elsewhere, text, "judge-read-v2")[1])
                reading_words = judge(post_quote="Model checks a physics result")   # the reading is not the post
                self.assertIn("not in this question's POST", check(kind, reading_words, text, "judge-read-v2")[1])
                self.assertIn("not in this question's POST",
                              check(kind, judge(post_quote="https://example.com/paper"), text, "judge-read-v2")[1])
                self.assertIn("post_quote missing", check(kind, judge(), text, "judge-read-v2")[1])
                self.assertIn("empty", check(kind, judge(post_quote="  "), text, "judge-read-v2")[1])
                self.assertIn("shorter than", check(kind, judge(post_quote="Fable 5.2"), text, "judge-read-v2")[1])
                bad_story = judge(post_quote="black holes form very abruptly", story_quote="a physics breakthrough")
                self.assertEqual(check(kind, bad_story, text, "judge-read-v2")[1],
                                 "story_quote: not in this question's STORY")
                # no guide named: the kind's current one checks it
                self.assertIsNotNone(check(kind, cross, text)[1])

    def test_a_grounded_answer_is_accepted(self):
        for kind in ("pair", "join"):
            text = self.question(kind)
            with self.subTest(kind=kind):
                ok = judge(relation="different", post_quote="black holes  form very abruptly",   # folded: spaces, case
                           reason="The post is about a physics result, not Cursor shipping the model.")
                self.assertIsNone(check(kind, ok, text, "judge-read-v2")[1])
                self.assertIsNone(check(kind, dict(ok, post_quote="In 1983, Physicists showed"), text, "judge-read-v2")[1])
                self.assertIsNone(check(kind, dict(ok, post_quote="Black holes and Fable 5.2"), text, "judge-read-v2")[1])
                about = dict(ok, relation="mention", story_quote="Cursor added Claude Fable 5.2")
                self.assertIsNone(check(kind, about, text, "judge-read-v2")[1])
                self.assertIsNone(check(kind, dict(ok, story_quote=None), text, "judge-read-v2")[1])
                self.assertIsNone(check(kind, judge(relation="cant_tell", post_quote=""), text, "judge-read-v2")[1])
                # an answer of v1 (no quote) stays valid under v1
                self.assertIsNone(check(kind, judge(), text, "judge-read-v1")[1])

    def test_a_short_post_may_be_quoted_whole(self):
        from datetime import datetime, timezone
        from insight_core.markx import tasks
        at = datetime(2100, 3, 1, tzinfo=timezone.utc)
        anchor = tasks.Post("a1", "x", "Example", "s1", at, "Widget 4 is out", "Acme released Widget 4 today.")
        post = tasks.Post("p2", "x", "Example", "s2", at, "Widget 4!", "")
        text = tasks.pair_input(anchor, post, {})
        self.assertIsNone(check("pair", judge(post_quote="Widget 4!"), text, "judge-read-v2")[1])
        self.assertIn("shorter than", check("pair", judge(post_quote="Widget"), text, "judge-read-v2")[1])


class HeadlineMembers(unittest.TestCase):
    """A headline reads the story's core, not its earliest 6 posts regardless."""

    def post(self, i, source, title, hours):
        from datetime import datetime, timedelta, timezone
        from insight_core.markx import tasks
        return tasks.Post(id=f"p{i}", kind="x", source=source, source_id=source, title=title, text=title + " today",
                          at=datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(hours=hours))

    def test_a_big_storys_first_side_post_is_left_out_for_what_most_voices_report(self):
        from insight_core.markx import tasks
        side = self.post(0, "early", "Fine tune a harness for agents", 0)
        core = [self.post(i, f"s{i}", "Acme ships Nimbus 5.1", i) for i in range(1, 9)]
        copy = self.post(9, "s1", "Acme ships Nimbus 5.1", 10)            # s1's own copy: one line of s1 is enough
        shown = tasks.headline_members([side, *core, copy])
        self.assertEqual([p.id for p in shown], [f"p{i}" for i in range(1, 7)])
        self.assertNotIn("Fine tune a harness", tasks.headline_input([side, *core, copy]))

    def test_a_small_story_shows_every_post_earliest_first(self):
        from insight_core.markx import tasks
        ps = [self.post(i, f"s{i % 2}", f"Acme ships Nimbus {i}", -i) for i in range(5)]
        self.assertEqual([p.id for p in tasks.headline_members(ps)], ["p4", "p3", "p2", "p1", "p0"])


if __name__ == "__main__":
    unittest.main()
