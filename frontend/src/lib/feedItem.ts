/** Small helpers for feed rows, outside the component file so fast refresh keeps working. */

/** The DOM id of a feed row (`FeedList` focuses it on j/k). */
export function feedItemDomId(id: string) {
  return `feed-item-${id}`;
}
