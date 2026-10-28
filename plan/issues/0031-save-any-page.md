# 0031 — Save any page: a bookmarklet and "paste a URL"

Status: **built** (2026-10-28, not deployed). Roadmap §3 (owner idea), its two **S** ways in.
Read later (0022) landed with it in v9.3: every save goes to Later (see "Saved pages go to Later").

## Problem
A page worth reading that is not in any source (a link from a chat, an article on a site you
don't follow) has no way into INSIGHT. The owner wants to keep it there and read it like a post.

## Built
- **`POST /api/saved {url, title?}`** (`services/saved_service.py`). The page is read with the
  dialog's own client (`KindHttp`, http and https only) as page watch reads an article:
  `page_watch.article_post`, one helper now shared with page watch's `post_from` (the full-text
  reader, the title less its "| Site" suffix, the page's date else now, `og:image` and the
  body's images). The post's identity is its whole address (where it redirected to).
  - A page that can't be read as an article (a JavaScript shell, a 403, no answer) is still
    saved, with the page's title, else the bookmarklet's, else the address, and the answer
    says so: `readable: false, reason: "HTTP 403" | "no article on the page" | …`, never the
    site's answer (0029 item 9).
  - A page already stored, under any source (its address or where it redirects, normalised:
    `utm_*` and a trailing slash don't count), is not stored again: `status: already` with that
    post.
  - The feed finder (0026) runs while the page is read; a feed that is not a source yet comes
    back as `feed: {url, title}`.
- **The Saved source**: platform `saved`, handle `Saved` (its name), created by the first save
  and written to sources.json at once (a source missing from it is deleted at the next start).
  Its kind, `saved` (`ingestion/kinds/saved.py`, first in the registry), has
  `PolitenessProfile(fetches=False)`: `decide_fetch` never finds it due, not even forced, so it
  shows as Scheduled with no next fetch, never due or failing; it has no archive. Saved pages
  are its unread posts, read from the rail and Sources like any source's.
- **The save page `/save`** (`pages/SavePage.tsx`): "Save to INSIGHT". From the bookmarklet
  (`?url=…&title=…`) it shows the page's title and site, **Save** and Cancel; from ⌘K
  ("Save a page…") a "Page address" field. Only Save, a POST from INSIGHT's own page, saves, so
  no website can save by itself. Then "Saved to INSIGHT" (Read it, Saved), "Saved, without its
  text" or "Already in INSIGHT"; "This site has a feed. Follow it?" with **Follow** (adds it
  through `POST /api/sources` and fetches it now); "Close tab" or "Save another page".
- **The bookmarklet** (`lib/savePage.ts`), a link to drag to the bookmarks bar, with one line
  ("Save pages from any site: drag … to your bookmarks bar, then click it on a page you want
  to keep.") on the save page and at the foot of Add source. It opens this INSIGHT's save page
  in a new tab:
  `javascript:(()=>{window.open("<origin>/save?url="+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title),'_blank','noopener')})()`
- **Sources**: the Saved source's kind reads "Saved pages", its note `pages you save`; its sheet
  says "The pages you save from any site. Never fetched by itself." and keeps Name, Tracks and
  Show in Main feed, without Fetch now, cadence, archive or fetch delay.

## Saved pages go to Later (v9.3, with 0022)
The owner's decisions in 0022: a saved page goes to **Later** by default and **sorts by when it
was saved**, not by the article's own date.
- `SavedService.save` takes the save time once (`clock`) and calls 0022's
  `ReaderService.set_later([post_id], True, at=<save time>)` for the post it saved, and for the
  post already stored on an "already" save (a post already in Later keeps its time).
- The feed sorts by `COALESCE(published_at, fetched_at)`, so the simplest correct option is to
  date a new saved post by its save time: `published_at` is the save time (also what the byline
  and the row show) and the page's own date is kept as `metadata.article_published_at`. No
  second sort key, no migration. A page already stored keeps its date: only Later changes.
- The save page says so: "<title> is in Saved and in Later, unread", "It's in Later" (a link to
  `/?filter=later`).
- Tests: `test_saved.py` (a save is in Later at the save time and dated by it; two saves sort by
  when saved, not by their articles' dates, and top the Main feed; an "already" save goes to
  Later and keeps its date); `SavePage.test.tsx` (the Later wording and link).

## Tests
- Backend `tests/test_saved.py`: the kind (resolved first, never due even forced or new, health
  Scheduled, no archive); reading a page (the article in full, a redirect, a JS shell, a 403 with
  the bookmarklet's title and no body in the reason, no title at all); the route on the scratch
  DB (an unread post of the Saved source, the source created once and exported once, a stored
  page not stored again, the unreadable answer, the feed offered and not offered once followed,
  only web addresses).
- Frontend `pages/SavePage.test.tsx`: the confirm page from the query, Save POSTs, already,
  unreadable, the feed nudge, an error, ⌘K's field and entry, the bookmarklet's href and what
  it opens; `sourceList.test.tsx`: the Saved source's kind and note.

## Limits
- One page per save; a page that needs a browser keeps only its title and link.
- The save waits for the page and the feed finder (under about 10 s).
- The share sheet, an extension and email-in (roadmap §3) are not built.
