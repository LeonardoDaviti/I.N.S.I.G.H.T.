/**
 * Byline: who wrote a post, via whom, quoting whom; the one formatter every view uses. The server's
 * utils/byline.py decides from stored fields (`author`, `via`, `quoting`). Display only: who a post counts as (a
 * voice) is decided elsewhere.
 *
 *   own post              -> "Feed"
 *   repost / forward      -> "@acme via Feed"
 *   quote                 -> "Feed, quoting @other"
 *
 * An author that is a source is named through `sourceLabel` (never a raw feed URL).
 */
import type { Repost } from '../services/api';
import { sourceLabel } from './sourceLabel.ts';

export interface Byline {
  author: string | null;
  via: string;
  quoting: string | null;
}

type HasByline = { byline?: Byline | null };

/** The line: "@acme via Feed, quoting @other"; the feed alone for its own post. `source` when no byline came. */
export function bylineText(byline: Byline | null | undefined, source?: string | null): string {
  const feed = sourceLabel(byline?.via || source);
  const who = byline?.author ? `${sourceLabel(byline.author)} via ${feed}` : feed;
  return byline?.quoting ? `${who}, quoting ${byline.quoting}` : who;
}

/** Who wrote it, in one name: the original author, else the feed. */
export function bylineName(post: HasByline & { source_display_name?: string | null }): string {
  return post.byline?.author ? sourceLabel(post.byline.author) : sourceLabel(post.byline?.via || post.source_display_name);
}

/** Whether the feed carried another's post (a repost or a forward): the line then names the feed as the carrier. */
export const carried = (post: HasByline) => Boolean(post.byline?.author);

/** "↻ from @tl_codex"; "↻ @toolsmith_pete, from @tl_codex" when other accounts of yours reposted it too;
 *  ", quoting @x" when it quotes one; null for the feed's own post that quotes none. */
export function carriedLine(post: HasByline & { repost?: Repost | null }): string | null {
  const b = post.byline;
  if (!b) return null;
  const others = post.repost?.by.length ? `@${post.repost.by.join(', @')}, ` : '';
  const from = b.author ? `↻ ${others}from ${sourceLabel(b.author)}` : null;
  const quote = b.quoting ? `quoting ${b.quoting}` : null;
  return from && quote ? `${from}, ${quote}` : from ?? quote;
}
