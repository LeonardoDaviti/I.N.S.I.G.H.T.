"""The Mark X story view with its perspectives and sheet (issue 0119 B6), and the owner's label buttons on them (B7).

`story_view` is what `/markx/stories/<id>` reads: the story, its sheet, each member's line (label, sign, new facts,
copies folded) and the owner's labels; the header states the measured accuracy: the lab's (2026-11-05, unseen
stories) until the owner has LAB_UNTIL labels, then the owner's own, with Wilson intervals.

Labels (mx_labels, keep everything: a changed answer is a new row, the newest counts):
  - item_kind `perspective`, a = story, b = post; answer `right`, `wrong`, or the right label (one of the five);
    note: JSON {"shown": the label shown, "row": the mx_perspectives row}, so a label keeps what it was about;
  - item_kind `fact`, a = story, b = post; answer `right`, `not_new`, `not_true` (not true to the post) or
    `not_about` (not about this story); note: "<index>: <the fact's text>".
labeller 'owner', split 'test': perspectives are unseen by construction and nothing is tuned on these labels
(0119 B7). `accuracy` reports them per label and for new facts against the lab's numbers.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from insight_core.markx import repo
from insight_core.markx.labels import wilson
from insight_core.markx.perspectives import LABELS, WORTH, load_members, pub

SIGNS = {"original": "★", "new_facts": "+", "opinion": "~", "same": "=", "not_this_story": "×"}
FACT_ANSWERS = ("right", "not_new", "not_true", "not_about")
PERSPECTIVE_ANSWERS = ("right", "wrong") + LABELS
LAB = {"worth": 0.83, "four": 0.70, "new_facts": 0.62, "date": "2026-11-05",
       "text": "Experimental: on unseen stories about 83% right on worth opening, 62% on new facts (lab, 2026-11-05)."}
LAB_UNTIL = 50            # the owner's labels replace the lab's numbers from this many on


def _root(cur: Any, story_id: str) -> Optional[Dict[str, Any]]:
    seen = set()
    st = repo.get_story(cur, story_id)
    while st is not None and st.get("merged_into") and str(st["id"]) not in seen:
        seen.add(str(st["id"]))
        st = repo.get_story(cur, st["merged_into"])
    return st


def current(cur: Any, story_id: str) -> Dict[str, Dict[str, Any]]:
    cur.execute("""SELECT post_id::text, id::text, label, by, haiku_label, facts, claims, point, before, copies, dropped,
                          valid_from FROM mx_perspectives WHERE story_id = %s AND valid_to IS NULL""", (story_id,))
    return {r[0]: {"row": r[1], "label": r[2], "by": r[3], "haiku_label": r[4], "facts": r[5] or [], "claims": r[6] or [],
                   "point": r[7], "before": r[8], "copies": r[9] or [], "dropped": r[10], "at": r[11]}
            for r in cur.fetchall()}


def sheet_of(cur: Any, story_id: str) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT sheet, valid_from FROM mx_sheets WHERE story_id = %s AND valid_to IS NULL", (story_id,))
    r = cur.fetchone()
    return None if r is None else {**r[0], "at": r[1]}


def _fact_index(note: Optional[str]) -> Optional[int]:
    head = (note or "").split(":", 1)[0]
    return int(head) if head.isdigit() else None


def owner_labels(cur: Any, story_id: Optional[str] = None, labeller: str = "owner"
                 ) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], Dict[Tuple[str, str, int], str]]:
    """The newest perspective label per (story, post) and fact label per (story, post, index)."""
    cur.execute("""SELECT item_kind, a::text, b::text, answer, note FROM mx_labels
                    WHERE item_kind IN ('perspective', 'fact') AND labeller = %s AND (%s::uuid IS NULL OR a = %s::uuid)
                    ORDER BY created_at, ctid""", (labeller, story_id, story_id))
    persp: Dict[Tuple[str, str], Dict[str, Any]] = {}
    facts: Dict[Tuple[str, str, int], str] = {}
    for kind, a, b, answer, note in cur.fetchall():
        if kind == "perspective":
            try:
                meta = json.loads(note or "{}")
            except ValueError:
                meta = {}
            persp[(a, b)] = {"answer": answer, "shown": meta.get("shown")}
        else:
            n = _fact_index(note)
            if n is not None:
                facts[(a, b, n)] = answer
    return persp, facts


def _rate(k: int, n: int) -> Dict[str, Any]:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": round(k / n, 4) if n else None, "lo": round(lo, 4), "hi": round(hi, 4)}


def accuracy(cur: Any, labeller: str = "owner") -> Dict[str, Any]:
    """The owner's labels scored: the four labels (a `wrong` with no label given counts as wrong), worth opening (a
    bare `wrong` says nothing about it, so it is left out), each shown label's precision, and the facts."""
    persp, facts = owner_labels(cur, labeller=labeller)
    four = worth = worth_n = 0
    per: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    errors: Counter = Counter()
    for (_s, _p), got in persp.items():
        shown, ans = got.get("shown"), got["answer"]
        if shown not in LABELS:
            continue
        right = ans == "right" or ans == shown
        four += right
        per[shown][1] += 1
        per[shown][0] += right
        if ans == "right" or ans in LABELS:
            truth = shown if ans == "right" else ans
            worth_n += 1
            worth += (shown in WORTH) == (truth in WORTH)
            if not right:
                errors[f"{shown}->{truth}"] += 1
        else:
            errors[f"{shown}->?"] += 1
    n = sum(v[1] for v in per.values())
    fk = Counter(facts.values())
    out = {"labels": n, "fact_labels": sum(fk.values()), "lab": {k: LAB[k] for k in ("worth", "four", "new_facts", "date")},
           "four": _rate(four, n), "worth": _rate(worth, worth_n),
           "per_label": {lab: _rate(*per[lab]) for lab in LABELS if per[lab][1]},
           "facts": {**_rate(fk["right"], sum(fk.values())), "answers": dict(fk)},
           "errors": dict(errors.most_common())}
    out["new_facts"] = out["per_label"].get("new_facts", _rate(0, 0))
    out["source"] = "owner" if n >= LAB_UNTIL else "lab"
    if out["source"] == "owner":
        w, f = out["worth"], out["new_facts"]
        pc = lambda r: "?" if r["p"] is None else f"{round(100 * r['p'])}% ({round(100 * r['lo'])}–{round(100 * r['hi'])})"
        out["text"] = (f"Experimental: on your {n} labels {pc(w)} right on worth opening, {pc(f)} on new facts "
                       f"(lab: {round(100 * LAB['worth'])}%, {round(100 * LAB['new_facts'])}%).")
    else:
        out["text"] = LAB["text"]
    return out


def story_view(cur: Any, story_id: str) -> Optional[Dict[str, Any]]:
    """The story, its sheet and its members' lines (published order), or None when there is no such story."""
    st = _root(cur, story_id)
    if st is None:
        return None
    sid = str(st["id"])
    members = [str(m["post_id"]) for m in repo.current_members(cur, sid) if m["role"] == "member"]
    rows = current(cur, sid)
    sheet = sheet_of(cur, sid)
    copies = {c for r in rows.values() for c in r["copies"]}
    folded = {c: p for p, r in rows.items() for c in r["copies"]}
    ids = sorted(set(members) | set(rows) | copies)
    posts = load_members(cur, ids)
    persp, facts = owner_labels(cur, sid)
    lines = []
    for pid in sorted((p for p in set(members) | set(rows) if p not in folded and p in posts),
                      key=lambda p: (pub(posts[p]), p)):
        r = rows.get(pid)
        line = {"post": pid, "member": pid in members, "label": r["label"] if r else None,
                "sign": SIGNS.get(r["label"]) if r else None, "by": r["by"] if r else None,
                "worth": (r["label"] in WORTH) if r else None, "before": r["before"] if r else False,
                "point": r["point"] if r else None, "claims": r["claims"] if r else [],
                "copies": [c for c in (r["copies"] if r else []) if c in posts],
                "facts": [{"index": n, **f, "mine": facts.get((sid, pid, n))} for n, f in enumerate(r["facts"] if r else [])],
                "mine": persp.get((sid, pid))}
        lines.append(line)
    acc = accuracy(cur)
    cur.execute("SELECT id::text, url FROM posts WHERE id = ANY(%s::uuid[])", (ids,))
    urls = dict(cur.fetchall())
    return {
        "story": {"id": sid, "headline": st.get("headline"), "first_at": st.get("first_at")},
        "judged": bool(rows), "sheet": sheet,
        "header": {"text": acc["text"], "source": acc["source"], "labels": acc["labels"]},
        "members": lines,
        "counts": {"members": len(members), "worth": sum(1 for l in lines if l["worth"]),
                   "same": sum(1 for l in lines if l["label"] == "same"),
                   "copies": sum(len(l["copies"]) for l in lines), "unjudged": sum(1 for l in lines if l["label"] is None)},
        "posts": {p: {"id": p, "title": m.title, "source": m.src_name, "kind": m.kind, "at": pub(m).isoformat(),
                      "url": urls.get(p)} for p, m in posts.items()},
    }


def label_perspective(cur: Any, *, story: str, post: str, answer: str, note: Optional[str] = None,
                      labeller: str = "owner") -> Dict[str, Any]:
    """✓ (`right`), ✗ (`wrong`) or the right label in one tap, on a member's current perspective."""
    if answer not in PERSPECTIVE_ANSWERS:
        raise ValueError(f"{answer!r} is not one of {', '.join(PERSPECTIVE_ANSWERS)}")
    row = current(cur, story).get(post)
    if row is None:
        raise KeyError(f"{post} in {story}")
    meta = {"shown": row["label"], "row": row["row"], **({"note": note.strip()} if (note or "").strip() else {})}
    lid = repo.add_label(cur, item_kind="perspective", a=story, b=post, answer=answer, split="test",
                         note=json.dumps(meta, ensure_ascii=False), labeller=labeller)
    return {"id": str(lid), "story": story, "post": post, "answer": answer, "shown": row["label"]}


def label_fact(cur: Any, *, story: str, post: str, index: int, answer: str, note: Optional[str] = None,
               labeller: str = "owner") -> Dict[str, Any]:
    """✓ (`right`) or ✗ ("not new", "not true to the post", "not about this story") on one new fact."""
    if answer not in FACT_ANSWERS:
        raise ValueError(f"{answer!r} is not one of {', '.join(FACT_ANSWERS)}")
    row = current(cur, story).get(post)
    if row is None or not (0 <= index < len(row["facts"])):
        raise KeyError(f"fact {index} of {post} in {story}")
    text = f"{index}: {row['facts'][index].get('fact') or ''}"
    if (note or "").strip():
        text += f" — {note.strip()}"
    lid = repo.add_label(cur, item_kind="fact", a=story, b=post, answer=answer, split="test", note=text,
                         labeller=labeller)
    return {"id": str(lid), "story": story, "post": post, "index": index, "answer": answer}
