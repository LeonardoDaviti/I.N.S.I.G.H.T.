/**
 * The post read last, so the feed can select it again when the reader comes
 * back (spec §F.5: u/Esc returns "restoring scroll and selection"). The feed
 * remembers the post it opens, the post page each post j/k moves to. In memory
 * only: it lives as long as the tab's app session, like the cached feed itself.
 */
let lastPostId: string | null = null;

export function rememberSelection(postId: string): void {
  lastPostId = postId;
}

export function recallSelection(): string | null {
  return lastPostId;
}
