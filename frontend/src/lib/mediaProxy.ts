/**
 * Post images load through our API (issue 0006): GET /api/media fetches one when it is first
 * shown and the frontend nginx keeps it for 24 hours. So an image from a LAN bridge
 * (telegram.local) shows on any device, and an origin sees one request a day, not one per
 * view. Relative on purpose: it goes through nginx, where the cache is, even when
 * VITE_API_URL points the API calls elsewhere. Anything that is not http(s) (a design
 * fixture's data: URL) is left as it is.
 */
export function proxiedImage(postId: string | null | undefined, url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (!postId || !/^https?:\/\//i.test(url)) return url;
  return `/api/media?post=${encodeURIComponent(postId)}&url=${encodeURIComponent(url)}`;
}
