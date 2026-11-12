# 0178 — Dead sources found, Telegram forwards keep the channel's username, every source named (spec + built)

INSIGHT v10.16, slice N (Sources). Branch `v1016-sources` off main 784d232; not merged, not pushed. Migration **0121**.
Names below are invented. Every rule is a class, never a site.

## The problems

1. **A dead source nobody noticed.** A followed daily newsletter stopped on 9 Sep: it moved to another domain and its
   old domain's home page now redirects there. Its old feed still answered (stale, 20 old items, "healthy"), so no
   failure ever woke the source doctor (0036), and for two months nothing said so.
2. **Telegram forwards credited by name only.** The bridge writes a forwarded message's header as an RSS item's
   `<source url="https://t.me/<channel>/<post>">Channel title</source>`; the parser dropped it, so bridge posts stored no
   forward at all (36 bridge channels on the local copy: 0 rows with `forwarded_from`), and the native adapter (0132 C3)
   stored the channel's id and name, never its username. Pairing's voice rule (`pairing.counted_voice`, Mark IX's rule)
   matches `t.me/<username>` (`tasks.author_account`), so no forward could ever count as a followed channel's voice.
   The item shape is from the bridge's own source (TelegramRSS `Messages.php`/`Feed.php`: `source` with `url` and the
   channel's `title`; `t.me/<id>/<post>` when the channel has no username): the stored posts keep none of it.
3. **Sources without a name.** A source added without a display name (an import, Add several, a scout follow, a feed
   whose title the dialog didn't take) showed its feed address wherever a name is shown (Discover's voices, a post's
   source line). Server, 2026-11-12: **94 of 359** sources (saved pages aside) have no name.

## Built

### 1. Silent far beyond its rhythm (source doctor)
- **The rule** (`source_doctor.silent_beyond_rhythm`): silent when the newest post is older than
  max(5 × its measured mean gap, 14 days). A source whose cadence is not measured (no mean gap, tier `unknown`) is never
  silent here (0046's "quiet" mark covers it). Not measured: 5 gaps is a run of misses no rhythm makes by chance often;
  the floor keeps a busy source's quiet fortnight out.
- **When** (`SourceDoctor.after_success`, called by the runner after every fetch that worked, with its new posts): new
  posts clear a recorded silence; otherwise, at most once a week (`LOOK_SILENT_EVERY`), the newest post's time is read
  (`FetchStateRepository.last_post_at`, health's own expression) and the rule applied.
- **Where it went** (`source_doctor.where_it_went`, for the kinds whose address can move: generic RSS, page watch,
  Substack): where its address, its home page and its 3 newest posts' own pages now land (`get_start`'s final address;
  another site is recorded in `moved` {via, from, to}); then the feed finder (0026) on each landing site, then on its own
  home page. The first feed offered is not the source's address, publishes **after** the source's last post (alive), is
  readable, no saved search, and on the source's own site stays within its section (0036's `within_section`, so a
  multi-blog site's home feed is never another blog's replacement). Its latest titles and newest date come with it.
- **Kept apart** from the failure finding (a working fetch clears `doctor_finding`): `source_fetch_state.silent_checked_at`,
  `silent_finding` (migration 0121) {last_post_at, silent_days, usual_gap_days, looked, moved, replacement, stopped}.
- **Never switched by itself.** The owner taps **Switch to <address>** (the existing `POST /api/sources/{id}/switch`,
  `sources_service.switch_source`: keeps id, name, tracks, posts; it now clears the silence too) or **It stopped**
  (`POST /api/sources/{id}/silence/stopped`: recorded, not shown again until the source posts after its last post;
  nothing is switched off or deleted).
- **Health** (`operations_service.silent_fields`): each row's `silent` {days, usual_gap_hours, last_post_at, looked_at,
  moved, replacement}, None when not silent, off, failing (the failure doctor speaks then), saved pages, or stopped; a
  look made before a newer post is not shown. The summary counts `silent` (not a status).
- **UI.** The source list's row fact says "Silent 64 days (usually every 1.4d): new feed found / moved to <site>", before
  quiet; a secondary **Silent** chip filters them. The source sheet shows `SilentNotice` (how long against its rhythm,
  where it landed, the feed found with its latest titles, Switch to / It stopped). Discover's Sources tab lists them
  under "Sources you follow that went silent" (`SilentSources`, read from source health).

### 2. Telegram forwards keep the username
- `parsing.rss_source` reads an RSS item's `<source url>` (as `origin_item`, transient); `telegram_rss.forwarded_from`
  turns it into `metadata.forwarded_from` {username, name, post, url} (the native adapter's shape), `channel_id` for a
  channel known by id only, nothing for a forward of the channel itself or a source that is no Telegram post. The name is
  the channel's title, else `@username` (`tasks.author_account` needs one). Another kind ignores `origin_item`.
- The native adapter adds the username (and the title, when the header has no name) from Telethon's
  `message.forward.chat`, no extra request; still behind `INSIGHT_TELEGRAM_FORWARDS` as before.
- Nothing in Mark X changed: `tasks.author_account` → `t.me/<username>`, `pairing.counted_voice` maps it to the source
  following that channel (tested end to end with `SourceFacts.of`). Stored bridge posts gain it when re-fetched (the
  upsert writes the feed's metadata); older ones by an archive.

### 3. Every source named
- `ingestion/source_names.py`: `clean_name` (entities and spaces tidied; a "| RSS Feed" / "- Atom" tail dropped; no name
  from a generic word — Feed, Blog, Home, RSS — or an address with a scheme or a path; a site calling itself by its host
  keeps it); `own_name` (a feed: its `<title>`, else the home page's og:site_name / `<title>`; a followed page: its site's
  name, else its own title; a subreddit: `r/<name>`; a feed that doesn't answer asks nothing more).
- **At add** (`POST /api/sources`, `_name_new_source`): no name given → its own name, written only where none is set
  (`SourcesRepository.name_if_unnamed`: one UPDATE whose WHERE is the guard). The answer carries `display_name`.
- **At a fetch** (every add path: import, Add several, scout): generic RSS reads its feed's own title for an unnamed
  source (`FetchedPosts.title`, `parsing.feed_channel_title`, no request), and the runner names it
  (`DbInspectionRefresher.named`, same guard).
- **The repair** (`python -m insight_core.scripts.repair_source_names`, dry run by default, `--apply`, `--no-fetch`,
  `--source`): every unnamed source, saved pages aside: its address's name, else a named source of the same *platform*
  account (a native channel and the bridge's feed of it; never a website's sections), else `own_name`, one source at a
  time 1 s apart. INSIGHT stores no feed title, so the repair asks the sites. Never writes over a name.

## Measured (read-only)
- **Server, GETs 2026-11-12** (`/api/sources`, `/api/sources/health`): 359 sources; **94 unnamed** (86 feeds, 6 followed
  pages, 2 subreddits). The rule would mark **25** sources silent now (several long-stopped personal blogs, 4 YouTube
  channels and 3 Telegram channels, which get the notice with It stopped only: their address can't move). The newsletter of
  problem 1 was switched by hand on the server today, so it is not among them.
- **Repair dry-run evidence** (the server's own read-only `POST /api/sources/find-feed` on each of the 86 unnamed
  feeds, 1 s apart, the title its finder read put through `clean_name`): **75 named by their feed's own title** (2
  tidied: a "RSS Feed" tail dropped), plus the **2 subreddits** by their address: **77 of 94 certain**. Left to the
  repair's other steps: 6 Substack feeds (the finder answers "direct" with no title; `own_name` reads the feed's own
  title), 1 feed with an empty title (its home page's name), 4 the server's finder could not read (blocked or
  timing out: they may stay unnamed), and the 6 followed pages (their site's name; not measurable through the finder).
  The repair itself runs on the server (`--apply` after the owner reads the dry run); the fetch path names an unnamed
  feed by itself at its next full (not 304) read.

## Tests
`test_sources_0178` (50): the rule (daily, weekly, unmeasured, no post); where it went (home redirect → new site's live
feed, the address redirecting, a newest post's page, a feed no newer than the last post never offered, a new feed on its
own site, another section's feed refused, nothing answering); the doctor (finding recorded, **never a switch**, within
rhythm asks nothing, new posts clear, once a week, It stopped holds, unmeasured, a kind that can't move); the runner
shows a working fetch with its new posts; health (offer, before a look, stale look hidden, stopped/failing/off, summary);
DB (health row → It stopped route → hidden, nothing switched; 404; Switch clears the silence); Telegram (the source
element, id-only, own channel, generic feed not stored, titleless, the kind's metadata, the native username, Pairing's
voice rule matching the followed channel and not a stranger); names (clean_name, own_name by feed / site / page /
subreddit / unanswered / not asked, the fetch's title only for an unnamed source, the refresher's guard, the repo guard,
the repair's dry run, `--apply`, `--no-fetch`, same account, never over the owner's name, the add route).
Frontend: `silentNotice.test.tsx` (8). Summary tests updated for `silent`.

## Left open
- The rule flags long-stopped personal blogs too (correctly silent); It stopped is the owner's answer. Measure on the
  server after deploy how many offers are right (the switch is never automatic).
- A move announced only in a post's text (no redirect, no new feed on the home page) is not read: a meaning-level fix.
- A native Telegram channel with no named bridge source keeps its handle as its label.
