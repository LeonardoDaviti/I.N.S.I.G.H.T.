import type { FeedStory, Repost, StoryOrigin, StoryPost, SuggestedSource } from '../services/api';
import { plural } from './format.ts';
import { sourceLabel } from './sourceLabel.ts';
import { SAVE_PATH } from './savePage.ts';

/**
 * A line of a story's tree (issue 0064): its outside origin, another post, the post you are on, or who
 * reposted the tweet above (issue 0068). `under`: on a line at the deepest indent, its parent's name,
 * shown on a phone in place of more indent (issue 0068).
 */
export type StoryLine =
  | { kind: 'page'; origin: StoryOrigin; depth: number }
  | { kind: 'post'; post: StoryPost; depth: number; under?: string }
  | { kind: 'self'; depth: number; under?: string }
  | { kind: 'reposts'; by: string[]; depth: number };

/** Two levels of indent at most: deeper posts are listed under the second level. */
const MAX_DEPTH = 2;
const PAGE = '\u0000origin';

/**
 * The story as a small tree (issue 0064): the origin first, then its children, then theirs, each
 * level in time order. `selfId` is the row or the post page the list belongs to: when it is the
 * origin it is not repeated (the list holds what came from it, one level less indented);
 * otherwise it is a `self` line in its place. A story without a tree (before the job drew it,
 * News) lists its posts as before, flat. A thread's replies (issue 0066) keep their parent's indent,
 * so a thread reads as a list, in its order.
 */
export function storyTree(story: FeedStory, selfId: string, selfAt?: string | null, selfName = ''): StoryLine[] {
  const hasTree = Boolean(story.origin) || Boolean(story.parent_reason)
    || story.posts.some((post) => Boolean(post.parent_reason));
  const lines: StoryLine[] = [];
  const add = (line: StoryLine, by?: string[] | null) => {
    lines.push(line);
    if (by?.length) lines.push({ kind: 'reposts', by, depth: line.depth });
  };
  if (!hasTree) {
    for (const post of story.posts) add({ kind: 'post', post, depth: 0 }, post.reposted_by);
    return lines;
  }
  const parentOf = (parentId: string | null | undefined, reason: string | null | undefined) =>
    parentId ?? (reason ? PAGE : null);
  type Node = { id: string; at: string; parent: string | null; post?: StoryPost };
  const nodes: Node[] = [
    { id: selfId, at: selfAt ?? '', parent: parentOf(story.parent_id, story.parent_reason) },
    ...story.posts.map((post) => ({ id: post.id, at: post.sort_at, parent: parentOf(post.parent_id, post.parent_reason), post })),
  ];
  const ids = new Set(nodes.map((node) => node.id));
  const root = story.origin ? PAGE : (nodes.find((node) => node.parent === null)?.id ?? selfId);
  const children = new Map<string, Node[]>();
  for (const node of nodes) {
    if (node.id === root) continue;
    // A parent the list doesn't hold (or a second origin) hangs from the root.
    const parent = node.parent && (node.parent === PAGE ? root === PAGE : ids.has(node.parent)) ? node.parent : root;
    children.set(parent, [...(children.get(parent) ?? []), node]);
  }
  // The row (or page) that is the origin is already above the list: its children are the list's first level.
  const offset = root === selfId ? 1 : 0;
  const seen = new Set<string>([root]);
  const nameOf = (id: string) => story.posts.find((p) => p.id === id)?.source_display_name ?? selfName;
  const walk = (id: string, depth: number) => {
    const kids = [...(children.get(id) ?? [])].sort((a, b) => a.at.localeCompare(b.at));
    for (const kid of kids) {
      if (seen.has(kid.id)) continue;
      seen.add(kid.id);
      const shown = Math.min(depth + 1, MAX_DEPTH) - offset;
      const under = shown === MAX_DEPTH ? nameOf(id) : undefined;
      add(kid.post ? { kind: 'post', post: kid.post, depth: shown, under } : { kind: 'self', depth: shown, under },
        (kid.post ?? story).reposted_by);
      walk(kid.id, (kid.post ?? story).parent_reason === 'thread' ? depth : depth + 1);
    }
  };
  if (root === PAGE && story.origin) lines.push({ kind: 'page', origin: story.origin, depth: 0 });
  else if (!offset) {
    const post = story.posts.find((p) => p.id === root);
    if (post) add({ kind: 'post', post, depth: 0 }, post.reposted_by);
  } else if (story.reposted_by?.length) lines.push({ kind: 'reposts', by: story.reposted_by, depth: 0 });
  walk(root, 0);
  return lines;
}

/** "openai.com · Introducing GPT-6.1 Terra · linked by 14": an outside origin's line. */
export function originLabel(origin: StoryOrigin): { site: string; title: string; linkedBy: string } {
  let site = origin.url;
  try {
    site = new URL(origin.url).hostname.replace(/^www\./, '') || origin.url;
  } catch { /* the address as it is */ }
  return { site, title: origin.title?.trim() || origin.url.replace(/^https?:\/\/(www\.)?/, ''), linkedBy: `linked by ${origin.linked_by}` };
}

/** Opening an outside origin: Save any page (issue 0031) on its address, saving nothing until you press Save. */
export function originHref(origin: StoryOrigin): string {
  const params = new URLSearchParams({ url: origin.url });
  if (origin.title) params.set('title', origin.title);
  return `${SAVE_PATH}?${params.toString()}`;
}

/** The names a folded story's row shows before "+N" (issue 0050), and a News row (issue 0051). */
const NAMES_SHOWN = 2;

/** "Anthropic, Simon Willison, +1": a story's sources in the order they covered it, two named. */
export function coveredNames(story: FeedStory): string {
  const all = story.sources.map((source) => sourceLabel(source.name));
  const more = all.length - NAMES_SHOWN;
  return `${all.slice(0, NAMES_SHOWN).join(', ')}${more > 0 ? `, +${more}` : ''}`;
}

/** "covered by 3 · Anthropic, Simon Willison, +1": every source of the story, in the order they covered it;
 *  "Thread · 6 posts" for one account's thread (issue 0066). */
export function coveredBy(story: FeedStory): string {
  if (story.thread) return `Thread · ${story.posts.length + 1} posts`;
  return `covered by ${story.sources.length} · ${coveredNames(story)}`;
}

/** "↻ reposted by @steipete, @badlogicgames": under a tweet in "covered by" (issue 0068). */
export const repostedBy = (by: string[]) => `↻ reposted by @${by.join(', @')}`;

/** "↻ @steipete, from @badlogicgames": who reposted a tweet, and its author (issue 0066). */
export function repostLine(repost: Repost): string {
  return `↻ @${repost.by.join(', @')}, from @${repost.author}`;
}

/** The names a suggestion's reason shows before "+N". */
const VOICES_SHOWN = 3;

/** Discover: "linked by 6 of your sources (Simon Willison, Anthropic, One Useful Thing, +3) · 9 articles",
 *  and " · 2 classics" when it holds some (issue 0051). */
export function suggestionReason(s: SuggestedSource): string {
  const names = s.voice_names.map((name) => sourceLabel(name));
  const more = names.length - VOICES_SHOWN;
  const who = `${names.slice(0, VOICES_SHOWN).join(', ')}${more > 0 ? `, +${more}` : ''}`;
  const classics = s.classics ? ` · ${plural(s.classics, 'classic')}` : '';
  return `linked by ${s.voices} of your sources (${who}) · ${plural(s.article_count, 'article')}${classics}`;
}
