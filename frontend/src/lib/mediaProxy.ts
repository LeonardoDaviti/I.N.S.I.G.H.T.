/**
 * Post images load through GET /api/media, kept 24 hours by the frontend nginx: a LAN bridge's image shows on any
 * device and an origin sees one request a day. Relative on purpose (through nginx's cache, even when VITE_API_URL
 * points elsewhere). Anything not http(s) is left as it is.
 */
export function proxiedImage(postId: string | null | undefined, url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (!postId || !/^https?:\/\//i.test(url)) return url;
  return `/api/media?post=${encodeURIComponent(postId)}&url=${encodeURIComponent(url)}`;
}
