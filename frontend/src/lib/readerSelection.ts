/**
 * The post read last, so the feed can select it again when the reader comes back (u/Esc). In memory only: it
 * lives as long as the tab's app session, like the cached feed.
 */
let lastPostId: string | null = null;

export function rememberSelection(postId: string): void {
  lastPostId = postId;
}

export function recallSelection(): string | null {
  return lastPostId;
}
