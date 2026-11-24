"""v10.47 (issue 0280 C): Discover's main list apart from the unfollowable and quiet rows (C1), reference and product
pages apart from publications (C2). Pure rules; the shapes are the
production answer's of 2026-11-24 (plan/issues/0280), the sites in them only as examples of their shape."""
import unittest

from insight_core.utils import discover_rules as R


def row(key, score, *, label=None, last_days=5.0, fit=None, language=None, interest=None, voices=5):
    s = {"key": key, "score": score, "voices": voices, "last_days": last_days}
    if label:
        s["follow_test"] = {"label": label, "at": "2026-11-01T00:00:00+00:00"}
    if fit:
        s["fit"] = fit
    if language:
        s["language"] = language
    if interest:
        s["interest"] = interest
    return s


class ApartSections(unittest.TestCase):
    def test_unfollowable_and_quiet_rows_leave_the_main_list(self):
        rows = [row("wire.example", 21.0, label="headlines"), row("paper.example", 19.0, label="blocked"),
                row("blog.example", 6.0, label="feed"), row("old.example", 9.0, last_days=200.0),
                row("new.example", 5.0)]
        main, apart = R.split(R.order(rows, reader=False))
        self.assertEqual([s["key"] for s in main], ["blog.example", "new.example"])
        self.assertEqual([s["key"] for s in apart["unfollowable"]["rows"]], ["wire.example", "paper.example"])
        self.assertEqual([s["key"] for s in apart["quiet"]["rows"]], ["old.example"])
        self.assertEqual(apart["quiet"]["total"], 1)

    def test_a_row_without_its_last_link_is_never_quiet(self):
        self.assertFalse(R.quiet({"key": "cited.example", "score": 1.0}))
        self.assertTrue(R.quiet({"key": "x", "score": 1.0, "last_days": R.QUIET_DAYS + 1}))
        self.assertFalse(R.quiet({"key": "x", "score": 1.0, "last_days": R.QUIET_DAYS}))

    def test_judged_follow_keeps_a_quiet_row_in_the_main_list(self):
        rows = [row("old.example", 3.0, last_days=200.0, fit="follow"), row("a.example", 9.0)]
        main, apart = R.split(R.order(rows, reader=False))
        self.assertEqual([s["key"] for s in main], ["old.example", "a.example"])
        self.assertEqual(apart["quiet"]["total"], 0)

    def test_order_clears_a_stale_section_mark(self):
        s = row("a.example", 3.0, label="feed")
        s["section"] = "unfollowable"
        self.assertNotIn("section", R.order([s], reader=False)[0])


class ReferencePages(unittest.TestCase):
    REFERENCE = [
        "https://gptunnel.ru/model/gpt-6.2-sol", "https://claude.ai/login?returnTo=%2F%3F",
        "https://en.wikipedia.org/wiki/ChatGPT", "https://huggingface.co/unsloth/MiniMax-M3.1-Flash-GGUF",
        "https://artificialanalysis.ai/models/qwen3-8-27b",
        "https://claude.com/product/claude-code", "https://grok.com/?mode=build&referrer=website",
        "https://arena.ai/leaderboard/agent", "https://microsoft.com/en-ca/windows",
        "https://stackoverflow.com/questions/1218390/what-is-your-most-productive-shortcut-with-vim/1220118",
        "https://statista.com/chart/12059/uber-revenue-bookings-and-net-loss",
        "https://docent.transluce.org/dashboard/12f4deca-a470-48df-9e51-0f65821cfd91",
    ]
    PIECES = [
        "https://ft.com/content/45383d86-33c4-4d99-86e5-5e058d3567c1",
        "https://bloomberg.com/news/articles/2026-11-19/apple-is-working-on-ai-agent-for-device-control-apps",
        "https://bloomberg.com/features/2026-police-phone-tracking-advertising-tech",
        "https://united.mediaroom.com/news-releases?item=125496", "https://piped.video/watch?v=x1_4b_YKW_w",
        "https://qwen.ai/blog?id=qwen3.8-flash-next", "https://postgresql.org/about/news/postgresql-19-released-3449",
        "https://endorlabs.com/learn/agent-security-league-evaluating-the-security-of-a",
        "https://carta.com/data/startup-shutdowns-q1-2024", "https://knowledge.wharton.upenn.edu/article/x-y-z",
        "https://worldlabs.ai/blog/atlas", "https://x.com/someone/status/2117999036175188183",
    ]

    def test_reference_and_product_pages(self):
        for url in self.REFERENCE:
            self.assertTrue(R.reference_page(url), url)
            self.assertEqual(R.page_kind(url), "reference")

    def test_pieces_stay_pieces(self):
        for url in self.PIECES:
            self.assertFalse(R.reference_page(url), url)
            self.assertIsNone(R.page_kind(url))

    def test_a_site_of_reference_pages_is_a_reference(self):
        qa = [f"https://qa.example/questions/{n}/how-do-i-{n}" for n in range(10)]
        self.assertEqual(R.place_kind("qa.example", qa), "reference")
        news = [f"https://news.example/2026/11/{n}/a-story-{n}" for n in range(10)]
        self.assertIsNone(R.place_kind("news.example", news))

    def test_a_platform_account_is_no_reference_by_its_pages(self):
        posts = [f"https://x.com/acct/status/{n}" for n in range(1000, 1010)]
        self.assertIsNone(R.place_kind("x.com/acct", posts))


if __name__ == "__main__":
    unittest.main()
