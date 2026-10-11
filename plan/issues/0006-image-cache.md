# 0006 — Post images through a 24-hour cache

Status: **built** (owner, 2026-10-11). Owner's choice: cache what is viewed, and store nothing for good.

## Problem
- Posts store image *links* only. The browser loaded each one straight from its origin.
- Images on a LAN bridge (`telegram.local/media/...`) showed only on devices that can reach the bridge.
- Every view hit the origin again.

## Decision
Cache only what is viewed. Images are **not** stored permanently: preserving images for good was considered (~0.5 GB, then ~0.3 GB a month) and declined.

- `GET /api/media?post=<id>&url=<image>` fetches the image at the moment it is shown. The backend writes nothing to disk.
- The frontend nginx caches the answer:
  - `proxy_cache`, `inactive=24h`, `max_size=2g`;
  - an image not viewed for 24 hours is deleted by nginx's cache manager;
  - a rebuilt container starts with an empty cache.
- The browser also keeps each image for 24 hours (`Cache-Control: max-age=86400`).
- Failures are cached for 10 minutes, so a dead origin isn't asked again on every view.
- The frontend sends every image through this route:
  - the feed thumbnail,
  - the post's images,
  - the `<img>`s in the post text.

  `data:` URLs (design fixtures) are left alone.

## Not an open proxy
- **Only the post's own images:**
  - its `media_urls` images,
  - its feed thumbnail (a YouTube frame),
  - the `<img src>` and Markdown `![](...)` images of its body.

  Anything else is a 404, and no request is made.
- **Only public hosts:** a host that resolves to a private, loopback, link-local or CGNAT (100.64/10) address is refused. The exceptions are the LAN bridges:
  - `telegram.local` and `nitter.local`;
  - the hosts in `RSS_SKIP_TLS_VERIFY_HOSTS`;
  - the hosts in `INSIGHT_MEDIA_PRIVATE_HOSTS`.

  Bridges are fetched with their self-signed certificate, like ingestion fetches them.
- **Redirects are checked too:** at most 3, each target checked again.
- **What comes back must be an image:**
  - only `image/*` responses, up to 10 MB;
  - served with `nosniff` and a sandboxing CSP, so an SVG opened on its own runs nothing.

## Load
- Each image is fetched about once a day at most, only when it is shown.
- Disk: nginx's cache directory, bounded at 2 GB. Today it's tens of MB, for one reader.
