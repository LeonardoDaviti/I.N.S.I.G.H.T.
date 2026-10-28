"""GET /api/sources/export.opml (issue 0035): every source as an outline, grouped by track."""
from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import main
from insight_core.services import registry as services_registry
from insight_core.tests._asgi import call

INSIGHT = "{https://insight.local/opml}"

SOURCES = [
    {"id": "s1", "platform": "rss", "handle_or_url": "https://borretti.me/feed.xml",
     "settings": {"display_name": "Fernando Borretti"}},
    {"id": "s2", "platform": "rss", "handle_or_url": "https://www.anthropic.com/news",
     "settings": {"display_name": "Anthropic News", "page_watch": {"prefix": "/news/"}}},
    {"id": "s3", "platform": "rss", "handle_or_url": "https://gwern.net", "settings": {}},
    {"id": "s4", "platform": "telegram", "handle_or_url": "@ai_newz", "settings": {"page_watch": {}}},
]
FOLDERS = [{"id": "f-ar", "name": "AR glasses", "sort_order": 1}, {"id": "f-ai", "name": "AI & <ML>", "sort_order": 0}]
MEMBERS = {"s1": ["f-ar", "f-ai"], "s2": ["f-ai"]}


class ExportOpmlRouteTests(unittest.TestCase):
    def setUp(self):
        fake = SimpleNamespace(
            sources=SimpleNamespace(get_all_sources_with_settings=lambda: SOURCES),
            folders=SimpleNamespace(list_folders=lambda: FOLDERS,
                                    list_folders_for_source=lambda source_id: MEMBERS.get(source_id, [])),
        )
        self.addCleanup(services_registry.use, services_registry.use(fake))

    def export(self):
        status, headers, body = call(main.app, "GET", "/api/sources/export.opml")
        self.assertEqual(status, 200)
        self.assertIn("text/x-opml", headers["content-type"])
        self.assertIn('attachment; filename="insight-sources.opml"', headers["content-disposition"])
        return ET.fromstring(body)

    def test_tracks_in_their_order_then_the_sources_in_none(self):
        root = self.export()
        self.assertEqual(root.tag, "opml")
        self.assertEqual(root.get("version"), "2.0")
        self.assertEqual(root.findtext("head/title"), "INSIGHT sources")
        body = root.find("body")
        groups = [(o.get("text"), [c.get("xmlUrl") for c in o]) for o in body if o.get("xmlUrl") is None]
        # A source in two tracks is listed under the first; its category names both.
        self.assertEqual(groups, [("AI & <ML>", ["https://borretti.me/feed.xml", "https://www.anthropic.com/news"]),
                                  ("AR glasses", [])])
        loose = [o.get("xmlUrl") for o in body if o.get("xmlUrl") is not None]
        self.assertEqual(loose, ["https://gwern.net", "@ai_newz"])
        borretti = body.find("outline/outline")
        self.assertEqual(borretti.get("category"), "AI & <ML>,AR glasses")

    def test_an_outline_carries_its_name_and_page_watch(self):
        outlines = {o.get("xmlUrl"): o for o in self.export().iter("outline") if o.get("xmlUrl")}
        anthropic = outlines["https://www.anthropic.com/news"]
        self.assertEqual((anthropic.get("text"), anthropic.get("title"), anthropic.get("type")),
                         ("Anthropic News", "Anthropic News", "rss"))
        self.assertEqual(anthropic.get(f"{INSIGHT}displayName"), "Anthropic News")
        self.assertEqual(anthropic.get(f"{INSIGHT}pageWatchPrefix"), "/news/")
        self.assertEqual(anthropic.get("htmlUrl"), "https://www.anthropic.com/news")
        gwern = outlines["https://gwern.net"]
        # No name: the address is the text, and no INSIGHT attributes.
        self.assertEqual(gwern.get("text"), "https://gwern.net")
        self.assertIsNone(gwern.get(f"{INSIGHT}displayName"))
        self.assertIsNone(gwern.get(f"{INSIGHT}pageWatchPrefix"))
        self.assertIsNone(gwern.get(f"{INSIGHT}platform"))
        # A page followed with the path inferred: the attribute is there, empty.
        telegram = outlines["@ai_newz"]
        self.assertEqual(telegram.get(f"{INSIGHT}pageWatchPrefix"), "")
        self.assertEqual(telegram.get(f"{INSIGHT}platform"), "telegram")


if __name__ == "__main__":
    unittest.main()
