/** News rows' discussion counts (0280): which posts a row asks about, and its "discussion: N points". */
import type { FeedItem } from '../services/api';
import type { MarkxDiscussionCounts } from '../services/markx';
import { plural } from './format';

/** A row's posts: its lead, then the story's (the discussion counts read these). */
export function rowPosts(item: FeedItem): string[] {
  return [item.id, ...(item.story?.posts.map((p) => p.id) ?? [])];
}

/** "discussion: N points": the points the worker read in the row's posts' threads, summed; null for none. */
export function discussionWords(item: FeedItem, counts: MarkxDiscussionCounts | undefined): string | null {
  if (!counts) return null;
  const n = [...new Set(rowPosts(item))].reduce((sum, id) => sum + (counts[id]?.points ?? 0), 0);
  return n ? `discussion: ${plural(n, 'point')}` : null;
}
