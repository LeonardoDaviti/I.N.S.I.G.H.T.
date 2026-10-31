"""Names that surge, joins that hold (issue 0070, part A).

- A name's burst is made of the sources followed for the whole 30 days before it: a newer source's
  posts join it but don't start it, make it or age the name; 2+ of its voices didn't say it then.
- A later burst of 3+ voices new to a name surges too, unless a few voices keep saying it.
- Titles are compared as plain letters (NFKC), and a word glued to another script's capital splits.

The rules as pure functions; the job on the database in one transaction per test, rolled back.
"""
from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.tests.test_news import LONG_AGO, T0, followed, post
from insight_core.utils.news_rules import names, surges
from insight_core.utils.story_rules import title_key


def said(source, hours, title="Gemini 4 Carbon is coming", n=1):
    return [post(f"{source}{hours}-{i}", source, hours=hours + i, title=title) for i in range(n)]


def launch(*sources, hours=0, title="Gemini 4 Carbon is here"):
    return [post(f"{s}@{hours}", s, hours=hours + i, title=title) for i, s in enumerate(sources)]


class NameEvidenceTests(unittest.TestCase):
    def test_a_newer_source_joins_a_burst_but_doesnt_make_or_age_it(self):
        # pankajkumar_dev, added 13 days before, leaked the name 11 times; then the launch.
        leaks = said("pankaj", -24 * 9, n=11)
        everyone = {**followed("s1", "s2", "s3"), "pankaj": T0 - timedelta(days=13)}
        [found] = [s for s in surges(leaks + launch("s1", "s2", "s3", "pankaj"), everyone) if s.name == "gemini 4 carbon"]
        self.assertEqual(found.posts, ["s1@0", "s2@0", "s3@0", "pankaj@0"], "the leaks don't age it; the launch post joins")
        self.assertEqual([s.name for s in surges(launch("s1", "s2", "pankaj", "pankaj"), everyone)], [],
                         "a newer source's posts don't make the 3 posts")
        self.assertEqual([s.name for s in surges(leaks + launch("pankaj", "s1", "s2", "s3"), everyone)
                          if s.name == "gemini 4 carbon"], ["gemini 4 carbon"], "nor start it: it starts at s1")

    def test_two_of_its_voices_are_new_to_the_name(self):
        everyone = followed("s1", "s2", "s3")
        once = said("s1", -100)
        self.assertEqual(surges(once + launch("s1", "s2", "s1"), everyone), [], "said once by s1: s2 alone is new")
        self.assertEqual([s.name for s in surges(once + launch("s1", "s2", "s3"), everyone)], ["gemini 4 carbon"])


class NameWaveTests(unittest.TestCase):
    def test_a_later_wave_of_three_new_voices_surges(self):
        # Mistral Large 4: launched on 6 Oct, open weights on 29 Oct.
        everyone = followed(*[f"s{i}" for i in range(1, 8)])
        first = launch("s1", "s2", "s3", title="Mistral Large 4 is out")
        weights = launch("s4", "s5", "s6", "s7", hours=24 * 23, title="Mistral Large 4 is now open weight")
        self.assertEqual([(s.name, s.posts) for s in surges(first + weights, everyone) if s.name == "mistral large 4"],
                         [("mistral large 4", ["s1@0", "s2@0", "s3@0"]),
                          ("mistral large 4", ["s4@552", "s5@552", "s6@552", "s7@552"])])
        self.assertEqual([s.at for s in surges(first + weights[:3], everyone) if s.name == "mistral large 4"], [T0],
                         "3 new voices, as many as the 30 days before: a few voices saying it again")
        two_new = launch("s1", "s4", "s5", hours=24 * 23, title="Mistral Large 4 is now open weight")
        self.assertEqual([s.at for s in surges(first + two_new, everyone) if s.name == "mistral large 4"], [T0],
                         "two new voices and one that said it: no wave")

    def test_a_series_a_few_voices_keep_saying_is_no_wave(self):
        # "Notes from May 2026", "rose bud thorn - may 2026": monthly posts of the same voices.
        everyone = followed(*[f"s{i}" for i in range(1, 9)])
        month = [p for i in range(1, 6) for p in said(f"s{i}", -24 * (25 - i), title="Notes from May 2026")]
        end = launch("s6", "s7", "s8", title="Notes from May 2026")
        self.assertEqual([s.name for s in surges(month + end, everyone) if s.at == T0], [],
                         "3 new voices, but 5 said it in the 30 days before")


class ComparedAsPlainLettersTests(unittest.TestCase):
    def test_styled_letters_are_plain_letters(self):
        self.assertIn("lfm3", names("Introducing 𝙻𝙵𝙼𝟹: our new generation"))
        self.assertEqual(title_key("𝙸𝚗𝚝𝚛𝚘𝚍𝚞𝚌𝚒𝚗𝚐 𝙻𝙵𝙼𝟹 every modality for you"),
                         title_key("Introducing LFM3 every modality for you"))

    def test_a_word_glued_to_another_scripts_capital_splits(self):
        self.assertIn("gemini 4 carbon", names("Google анонсировали Gemini 4 CarbonМодель заняла первое место"))
        self.assertIn("gpt-6.1 terra", names("OpenAI выпустили GPT-6.1 TerraНемного"))
        self.assertIn("openai codex 2", names("OpenAI Codex 2 is out"), "a capital inside one script stays in its word")


if __name__ == "__main__":
    unittest.main()
