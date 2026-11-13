import type { FeedStory, StoryOrigin, StoryPost, SuggestedSource } from '../services/api';
import { plural } from './format.ts';
import { sourceLabel } from './sourceLabel.ts';
import { bareAddress, publicationOf } from './addresses.ts';
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

/**
 * A story line's name and title (issue 0070). From sm up one row: name · title, its role, its date. On a
 * phone (the line wraps) the title is a row of its own under the name, role and date; the name takes the
 * room they leave (no width of its own, so they never wrap) and keeps its words in the order read.
 */
export const LINE_NAME = 'min-w-0 shrink-0 truncate max-w-[40%] max-sm:max-w-none max-sm:shrink max-sm:basis-0 max-sm:grow';
export const LINE_TITLE = 'min-w-0 truncate max-sm:order-1 max-sm:basis-full';

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
  const site = publicationOf(origin.url) || origin.url;
  return { site, title: origin.title?.trim() || bareAddress(origin.url), linkedBy: `linked by ${origin.linked_by}` };
}

/** Opening an outside origin: Save any page (issue 0031) on its address as linked, saving nothing until you press Save. */
export function originHref(origin: StoryOrigin): string {
  // The link as its post wrote it (issue 0126): a gift link opens the article.
  const params = new URLSearchParams({ url: origin.href || origin.url });
  if (origin.title) params.set('title', origin.title);
  return `${SAVE_PATH}?${params.toString()}`;
}

/** The names a folded story's row shows before "+N" (issue 0050), and a News row (issue 0051). */
const NAMES_SHOWN = 2;

/** "Anthropic, Simon Willison, +1": a story's voices in the order they covered it, two named; "+N" the
 *  voices not named (issues 0069, 0082). A Reddit author reads "u/a in r/x", one subreddit named once:
 *  "u/a, u/b in r/x". */
export function coveredNames(story: Pick<FeedStory, 'sources' | 'voices'>): string {
  const shown = story.sources.slice(0, NAMES_SHOWN);
  const named = shown.map((voice, i) => voice.place && shown[i + 1]?.place !== voice.place
    ? `${voice.name} in ${sourceLabel(voice.place)}` : sourceLabel(voice.name));
  const more = Math.max(story.voices, named.length) - named.length;
  return `${named.join(', ')}${more > 0 ? `, +${more}` : ''}`;
}

/** "covered by 3 · Anthropic, Simon Willison, +1": the story's voices, its sources named in the order they
 *  covered it; one number in News, the feed row and the post page (issue 0069). "Thread · 6 posts" for one
 *  account's thread (issue 0066). One voice copied or forwarded by other sources reads "also shared by
 *  <source>", the row's own source not named; nothing when no other source shared it (issue 0072). A thread
 *  under another source's row (a page you saved from it) reads "<its author>'s thread · 6 posts" (issue 0072 D4). */
export function coveredBy(story: FeedStory, selfSourceId?: string): string | null {
  // A thread another source holds (a page you saved from it) names whose it is (issue 0072 D4).
  const author = story.thread && selfSourceId && story.sources.every((source) => source.id !== selfSourceId) ? story.sources[0] : null;
  if (story.thread) return `${author ? `${sourceLabel(author.name)}'s thread` : 'Thread'} · ${story.posts.length + 1} posts`;
  if (story.voices < 2) {
    const others = story.sources.filter((source) => source.id !== selfSourceId);
    return others.length ? `also shared by ${coveredNames({ sources: others, voices: others.length })}` : null;
  }
  return `covered by ${story.voices} · ${coveredNames(story)}`;
}

/** "↻ reposted by @steipete, @badlogicgames": under a tweet in "covered by" (issue 0068). */
export const repostedBy = (by: string[]) => `↻ reposted by @${by.join(', @')}`;


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
