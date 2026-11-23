You read ONE post (an article, a release, a blog post) and the comment thread readers wrote about it on a discussion site (Hacker News, Lobsters). You tell a busy reader what the discussion ADDS beyond the post: what they would miss by reading only the post.

Input: POST (title), SITE, POST TEXT (cut), THREAD (the site, how many comments it has, how many are shown), then COMMENTS, best first, each on its own line: `[c<id>] <author>: <text>`, a reply as `[c<id>] <author>, reply to c<id>: <text>` (indented under its parent).

Answer ONE single-line JSON object:
{"id": "<the item id>", "stance": "<one line: how the thread as a whole receives the post, e.g. 'mostly agrees, adds that macOS and Windows already compress memory by default', 'skeptical: many say the benchmark is flawed'>", "points": [{"kind": "correction|counterpoint|experience|data|tool|question|context", "text": "<one or two sentences, in your words, stating what the comment(s) say>", "comments": ["c<id>", ...], "quote": "<an EXACT quote, 5-30 words, copied from the FIRST comment you cite>"}], "tools": [{"name": "<a tool, library, product, paper or site the comments recommend or use>", "url": "<its address exactly as a comment gives it, else null>", "what": "<what it is or does, in a few words, from the comments, else null>", "comments": ["c<id>", ...]}]}

Kinds of points:
- correction: a comment says the post is wrong or out of date on a fact, and says what is right.
- counterpoint: a substantive argument against the post's claim or approach (not mere dislike).
- experience: firsthand experience ("I run this in production...", "at my company we...") that confirms, limits or contradicts the post.
- data: a number, benchmark, measurement or source the post does not give.
- tool: an alternative or complementary tool/approach the comments recommend, with why (also list it in "tools").
- question: an important open question the thread raises and does not settle.
- context: history, prior art or background that changes how to read the post (e.g. "this was done in 1998 by...").

Rules:
- At most 8 points, the most useful first. Fewer is fine: a thread of jokes, off-topic arguments or "great post" adds nothing; then return "points": [] and say so in "stance".
- Every point cites 1-6 comment ids that appear in COMMENTS, exactly as written ("c50562008"). Cite only comments that actually say it.
- "quote" is copied character for character from the first cited comment (same words, same order, no "..." joins, not translated). Pick the words that carry the point.
- Say only what the comments say. Do not judge who is right, add outside knowledge, or repeat what the POST TEXT already says. If commenters disagree with each other, say so in the point ("others reply that...") and cite both sides.
- Write points as plain statements of what commenters report ("Several commenters note macOS has compressed memory since 2013"), never as your own claims.
- "tools": at most 12, each named in a cited comment; a link a comment gives goes in "url" exactly as written. No tools: [].
- Ignore moderation, meta-discussion about the site, and personal attacks.
