/** Small helpers for feed rows, outside the component file so fast refresh keeps working. */

/** The DOM id of a feed row (`FeedList` focuses it on j/k). */
export function feedItemDomId(id: string) {
  return `feed-item-${id}`;
}

/** 4:02:07 / 12:34 / 0:45 for video durations. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}
