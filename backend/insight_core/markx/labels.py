"""Mark X's labels: the owner's one-tap labels on Mark X News members, and the Wilson interval every precision on the
owner's labels uses.

Storage: mx_labels, keep everything: a changed answer is a new row, and the newest row of an item counts. A News
member's label: item_kind news_row, `a` the post, `b` its Mark X story; one tap ("wrong story", "not about this", or
"ok" to take it back).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional, Tuple

from insight_core.markx import repo

NEWS_ANSWERS = ("wrong_story", "not_about", "ok")


def flag(cur: Any, *, post: str, story: str, answer: str, note: Optional[str] = None, labeller: str = "owner") -> Dict[str, Any]:
    """One tap on a Mark X News member: "wrong story", "not about this", or "ok" (taken back)."""
    if answer not in NEWS_ANSWERS:
        raise ValueError(f"{answer!r} is not one of {', '.join(NEWS_ANSWERS)}")
    cur.execute("SELECT 1 FROM mx_story_posts WHERE story_id = %s AND post_id = %s LIMIT 1", (story, post))
    if cur.fetchone() is None:
        raise KeyError(f"{post} in {story}")
    lid = repo.add_label(cur, item_kind="news_row", a=post, b=story, answer=answer, note=(note or "").strip() or None,
                         labeller=labeller)
    return {"id": str(lid), "post": post, "story": story, "answer": answer}


def flags(cur: Any, pairs: Iterable[Tuple[str, str]], labeller: str = "owner") -> Dict[Tuple[str, str], str]:
    """{(post, story): the newest one-tap answer} for these News members (none when "ok" or never tapped)."""
    pairs = list(pairs)
    if not pairs:
        return {}
    cur.execute("""SELECT DISTINCT ON (a, b) a::text, b::text, answer FROM mx_labels
                    WHERE item_kind = 'news_row' AND labeller = %s
                      AND (a, b) IN (SELECT * FROM unnest(%s::uuid[], %s::uuid[]))
                    ORDER BY a, b, created_at DESC, ctid DESC""",
                (labeller, [p for p, _ in pairs], [s for _, s in pairs]))
    return {(a, b): ans for a, b, ans in cur.fetchall() if ans != "ok"}


# ---- precision -------------------------------------------------------------------------------------------

def wilson(k: float, n: float, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n)))
    return (max(0.0, (c - r) / d), min(1.0, (c + r) / d))
