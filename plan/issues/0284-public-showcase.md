# 0284 Public showcase (plan 2): a view-only INSIGHT on Cloudflare

Status: **spec, not started** (owner 2026-11-26: discussion only). Plan 2 of three (1 open source, 2 free hosted demo of
the owner's feed, 3 hosted subscription). Purpose: let people read INSIGHT and learn how they use it, to improve the
reading experience. All computation stays on the owner's server; Cloudflare only shows the export.

## Decided
- **Architecture:** INSIGHT exports JSON outward to Cloudflare R2; a separate public frontend build on Cloudflare Pages
  reads it through a small Worker (`/data/*`). No backend, tunnel or API reachable by visitors. Funnel rejected (no
  custom domain); a cloudflared tunnel to the live API rejected.
- **Export cadence:** every **hour**, only changed stories and rows uploaded (hash per file).
- **Access:** no login, an open link (like AINews, news.smol.ai); `noindex` + robots.txt during the beta.
- **Address:** `<name>.pages.dev` first; a domain (Cloudflare Registrar, ~$10/yr) before going public.
- **Content only, with its clicks:** News → story → post card → entity → track brief/table. No settings of any kind,
  no search, nothing needing backend compute, no reading data, no personal ranking (global order only), no Mark X
  lab, no sources page.
- **Copyright:** headlines, sources, short excerpts, links to the originals; never full article text.
- **Pictures:** each article's own preview image linked from its original address (no copies, no proxy;
  `referrerpolicy=no-referrer`, lazy, hidden when it fails).
- **Public build:** `vite build --mode public` from the same code; private routes and every write/`/api` client left
  out of the bundle at build time; one data-layer switch reads `/data/*.json`.
- **Learning:** Cloudflare Web Analytics (no cookies); an outbound-click counter (`/go?u=`) and a feedback form, both
  stored in D1 by the same Worker; nothing personal kept; the About page says what is counted.

## Numbers (production, 2026-11-26)
- News: 804 rows, 765 stories, 233 sources. The internal News answer is 4.4 MB (it carries judge details the public
  export drops); a public `news.json` is estimated at ~0.5-1 MB. A story page is ~7.5 KB internally, ~3 KB public:
  ~2-5 MB for the News window's stories.
- Entities: ~64k exist; export only those named in exported stories (estimated a few thousand, ~1-3 KB each).
- R2 writes: hourly, changed only: ~36k/month (free: 1M). Reads: 10-50 testers ~300k/month (free: 10M).
  Storage: tens of MB (free: 10 GB). Worker: ~10k requests/day (free: 100k). Pages: a deploy per release (free: 500
  builds/month). D1: clicks and feedback, far under the free 100k writes/day.
- Within the News window: 38 posts from the owner's Saved pages, 96 from Reddit (decisions below).

## Open (the owner decides)
1. **Tracks:** which are exported. Today: Agentic Workflows, Cool 3D Projects, Cool Projects, Local Setups,
   My security & privacy, Security news, Security & Privacy. Recommended: all but **My security & privacy** (it lists
   the owner's own tools).
2. **Saved pages:** the owner's hand-saved pages appear in News (38 now). Show them as normal posts, or leave them
   out (they reveal what the owner reads)?
3. **Reddit:** 96 posts come through the owner's private feed. Recommended: headline + link to the public reddit.com
   address only; never any feed or token address.
4. **Time window:** News window only (as on the owner's News), or also older stories kept as pages once exported
   (keep everything)?
5. **Excerpt length:** recommended ~280 characters per post, none for paywalled sources.
6. **Name** of the Pages project (the `*.pages.dev` address) and the About text (what INSIGHT is, open source link,
   what is counted, a contact for takedown requests).
7. **Build and deploy:** from the owner's server automatically after each deploy, or by Claude with each release.
8. **Cloudflare account:** the owner creates the account, the Pages project, the R2 bucket and D1, and one API
   token scoped to that bucket + project only; the token lives on the server (never in git).

## Work, when started
1. Export job (backend): the files, the content rules in one place, changed-only upload, a manifest with a format
   version; its memory budget measured like the other jobs.
2. A leak test: every exported file is read and fails on a private field, a private track, full text or a token.
3. Public build (frontend): the data-layer switch, private parts out of the bundle, noindex, About, feedback button.
4. The Worker: `/data/*` from R2, `/go` click counter, `/feedback` into D1.
5. Cloudflare setup steps written for the owner; then an outside check of the public site (every private path
   absent, no full text, pictures, speed).
