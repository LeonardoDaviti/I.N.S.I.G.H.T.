# 0171 — Research's web search done by the worker (built, v10.15 part E)

Owner 2026-11-12: "we use Claude as our worker, so its agents have web search, which is enough for us now." 0162's
web-search step (finding a maker's accounts a site doesn't declare: "web search is supremacy") was a server-side
provider (SearXNG or Brave), off when unconfigured, so it never ran. Now, unconfigured, the step is asked of the Mark X
worker (Claude Code on the owner's device) with its web search tool.

Built on branch `v1015-websearch` from main 7b651e5. **Migration 0115** (`mx_research_runs.web_task_id`;
`mx_tasks.subject_kind` may be `research_run`). Mark X tables only. Not measured on real data (see "Measure").

## What changed

| # | What | Where |
|---|---|---|
| 1 | Provider selection: `INSIGHT_WEB_SEARCH=searxng` (+ URL) or `brave` (+ key) as before; **unset, `worker`, or a named provider without its address/key: the worker's** (`WorkerSearch`, name `worker`); `off`/`none`: no web search. `GET /api/markx/research/settings` says `web_search: "worker"` by default. | `markx/research_web.py` `web_search` |
| 2 | A new task kind `websearch`, guide `websearch-v1`, subject `research_run` (a = the run that first asked). Input: the maker's names (research's `maker_names`: identity's maker of the seed entity, a person/org seed, confirmed handles, a name seed; at most 2), what it is known for (the seed entity's label and type, else the seed), the addresses already confirmed (to tie results to, and to leave out), `Searches allowed: at most N`. No run id: the same question is one task (two runs of one seed share it and its answer). | `markx/schemas.py`, `markx/guides/websearch-v1.md`, `markx/research.py` `websearch_input` |
| 3 | Answer: `{candidates: [{url, title?, why}] (at most 15), queries: [..] (at most 5)}`. Server checks (`validate._websearch`): each url one http(s) address, no spaces, at most 500 characters, named once (www and a trailing slash folded); title and why one line, why not empty; each query one line. | `markx/schemas.py` `WEBSEARCH_SCHEMA`, `markx/validate.py` |
| 4 | The run waits: step `web` (`web_by_worker`) asks the task once (priority -1, like `identity`), spends the run's web searches when the task is new (`min(5, 11 - search_calls)`: the existing 5 a run within the 11 shared with discussion; 0 left: no task, the step says so), and is not done while the task is open or leased. `settle` counts the open task as waiting (status `waiting`); `tasks.record` → `research.after_websearch` sets the waiting runs back to `running`; the ingestion tick or the page's background advance goes on: the step adds the candidates and the identity graph reads them in the same advance. A failed task (3 invalid answers) closes the step with `failed` and an "unread" line. | `markx/research.py` `web_by_worker`, `after_websearch`, `settle`, `advance`; `markx/tasks.py` |
| 5 | Candidates only: each url `classify`d (an account, community, project or site; an article or post is dropped), never already in the graph, added at hop 2 with `how: web search (the worker's Claude) for <name>`, its `why` kept as `found_why` (shown, never given to the identity question, so the searcher's opinion does not vote). Then read and judged as 0162's step 3: the plain same-identity rules or one `identity` question; a name alone never counts. | `markx/research.py` `web_candidates` |
| 6 | The page's data: `run.web_search {by, waiting, asked}` (the provider, whether the run waits for the worker, the queries the worker ran). No UI change. | `markx/research.py` `web_view` |
| 7 | Worker: `websearch` in `DEFAULT_KINDS` (after `identity`), `PER_CALL websearch=1`. Its calls, and only its, run `claude -p --model haiku --tools WebSearch --system-prompt <guide+schema> --output-format json --no-session-persistence --strict-mcp-config --allowedTools WebSearch --max-turns 8`: the web search tool is the only tool available (`--tools`), allowed without a permission prompt (`--allowedTools`; headless, a prompt would deny it), no WebFetch (the server reads every page itself), turns capped (5 searches, the answer, slack; a call that hits the cap fails as any error and is retried once). Every other kind keeps `--tools ""`. | `scripts/markx-worker` `claude_argv`, `call`, `ask` |

## Tests

- `test_markx_research` (+7): the kind, guide (a name alone not enough, never fetch), schema and every check; provider
  selection (worker by default and when named, `off`, a named provider unconfigured falls back to the worker, Brave and
  SearXNG when configured). On the test database (`WebByWorker`, discussion stubbed so the run's searches are the
  web's): asked once with the maker, the confirmed addresses and the cap in its input; the run waits (`waiting`, no
  `web` step, 5 searches spent, the page says waiting) and a second advance asks nothing more; the answer through the
  worker's API sets the run running; the next advance adds 2 of 4 candidates (an article dropped, a confirmed one not
  re-added), the one whose profile links the site confirmed by rule, the namesake asked and kept out by `no`; the same
  question shared by a second run with no wait and nothing spent; the cap (2 left → "at most 2", 0 left → no task, said);
  a failed task said and the step closed; SearXNG/Brave configured or `off` never ask the worker; the settings route.
- `test_markx_validate`: the kinds and subjects lists.
- Worker (`python3 -m unittest scripts.tests.test_markx_worker`, `TestWebSearch`, fake-claude): a default kind, one a
  call; `claude_argv` gives the web search tool, `--allowedTools WebSearch` and `--max-turns 8` to `websearch` only and
  `--tools ""` to every other default kind; a cycle of `websearch` and `read` (the fake checks each argv exactly and
  answers a web-search call as websearch-v1); an answer the schema refuses asked once more.
- Full backend suite: `scripts/test-backend.sh`.

## Cost (an estimate, not measured)

Claude Code's web search: $10 per 1,000 searches ($0.01 a search) on API billing (on the owner's subscription it counts
against the plan's usage instead), plus tokens: each search's results (roughly 3-8k tokens) enter the context and every
later turn reads them again (mostly as cache reads). With Haiku (about $1/M input, $0.10/M cache read, $5/M output) a
5-search question is roughly 30-60k input tokens: **about $0.03-0.08 a question (one a run), $0.01-0.02 a search**. The
worker logs each call's `cost_usd` and tokens (`kind: websearch`); read the first runs' figures from its log.

## Measure (on the owner's device and the server; not run here)

After deploy (migration 0115), with Mark X on: research the bare model name of 0162's test 2, then run the worker by
hand within a stated cap (`scripts/markx-worker cycle --kinds websearch,identity,track --batches 2`). Count, against the
11 channels found by hand: what the web search added, how many were confirmed (rule / Haiku), how many wrong (a
namesake confirmed, a platform's own page: must be 0), and the call's cost and turns from the worker log. Check
the first call's log for an `error_max_turns` or a permission denial (the flags not taking).

## Left off

- The worker answers with what Claude saw; the server never trusts it for identity, but the searches spent are the
  5 reserved at asking, not the number Claude ran (`queries` is reported and shown; not refunded).
- A re-run of the same seed reuses the earlier answer (one task per question); a fresh search needs another
  question (a changed confirmed set does it). A "search again" button is not built.
- No UI change on the research page beyond the data (`run.web_search`); the page's step list shows `web` when done.
- `--max-turns` is a hidden Claude Code flag (present in 2.1.321's binary, not in `--help`); the per-search count
  is not enforceable by the CLI, only by the guide and the turn cap.
- Discussion search (0162 step 7) still reads platform search feeds on the server; not moved to the worker.
