"""The reader's page corpus (issue 0032): how the reader does on it, and a refresh when a site redesigns.

Owner-run only; nothing runs it automatically.

    python -m insight_core.scripts.refresh_page_corpus                 # the stored pages: what fails
    python -m insight_core.scripts.refresh_page_corpus --fetch [name…] # read each page again, compare
    python -m insight_core.scripts.refresh_page_corpus --fetch --write # …and keep the new copies

--fetch downloads each page once (2 s apart, INSIGHT's User-Agent), trims it as the corpus
does and reports, per page, each expectation whose result changed between the stored copy
and the live page. --write replaces the stored copies and their fetch date; the
expectations themselves are only ever edited by hand (tests/fixtures/pages/expectations.json).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date
from typing import Dict, List, Optional

from insight_core.ingestion.http import DEFAULT_USER_AGENT
from insight_core.tests import _page_corpus as corpus

PAGE_DELAY_S = 2.0
TIMEOUT_S = 30


def _results(name: str, expected: dict, page: str) -> Dict[str, Optional[str]]:
    return corpus.problems(expected, corpus.read(page, expected["url"]))


def report() -> int:
    expectations = corpus.load_expectations()
    checks = failed = 0
    for name, expected in expectations.items():
        gaps = expected.get("known_gaps") or {}
        for check, problem in _results(name, expected, corpus.page_html(name)).items():
            checks += 1
            if problem:
                failed += 1
                print(f"{name}: {check}: {problem}" + (" (known gap)" if check in gaps else ""))
    print(f"{checks - failed} of {checks} expectations met on {len(expectations)} pages")
    return 0


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:   # noqa: S310 - the corpus's own https URLs
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def refresh(names: List[str], write: bool) -> int:
    expectations = corpus.load_expectations()
    unknown = [name for name in names if name not in expectations]
    if unknown:
        print(f"Not in the corpus: {', '.join(unknown)}", file=sys.stderr)
        return 2
    changed = 0
    for n, name in enumerate(names or list(expectations)):
        expected = expectations[name]
        if n:
            time.sleep(PAGE_DELAY_S)
        try:
            fresh = corpus.trim(_fetch(expected["url"]))
        except Exception as exc:  # noqa: BLE001 - one unreadable page is reported, not fatal
            print(f"{name}: could not be read ({exc})")
            continue
        before = _results(name, expected, corpus.page_html(name))
        after = _results(name, expected, fresh)
        moves = [f"  {check}: {'met' if before[check] is None else 'failed'} -> "
                 f"{'met' if after[check] is None else 'failed: ' + str(after[check])}"
                 for check in before if (before[check] is None) != (after[check] is None)]
        print(f"{name}: " + ("unchanged" if not moves else "changed\n" + "\n".join(moves)))
        changed += bool(moves)
        if write:
            (corpus.PAGES_DIR / f"{name}.html").write_text(fresh, encoding="utf-8")
            expected["fetched"] = date.today().isoformat()
    if write:
        _write_expectations(expectations)
    print(f"{changed} page(s) changed" + ("; the new copies are stored" if write else ""))
    return 0


def _write_expectations(expectations: dict) -> None:
    """One key per line, as the file is kept."""
    lines = ["{"]
    for n, (name, page) in enumerate(expectations.items()):
        lines.append(f"  {json.dumps(name)}: {{")
        for i, (key, value) in enumerate(page.items()):
            if isinstance(value, dict):
                inner = ",\n".join(f"      {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in value.items())
                text = "{\n" + inner + "\n    }"
            else:
                text = json.dumps(value, ensure_ascii=False)
            lines.append(f"    {json.dumps(key)}: {text}" + ("," if i < len(page) - 1 else ""))
        lines.append("  }" + ("," if n < len(expectations) - 1 else ""))
    lines.append("}")
    corpus.EXPECTATIONS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fetch", action="store_true", help="read the pages again and compare")
    parser.add_argument("--write", action="store_true", help="with --fetch: keep the new copies")
    parser.add_argument("names", nargs="*", help="pages to refresh (default: all)")
    args = parser.parse_args(argv)
    if args.write and not args.fetch:
        parser.error("--write needs --fetch")
    return refresh(args.names, args.write) if args.fetch else report()


if __name__ == "__main__":
    sys.exit(main())
