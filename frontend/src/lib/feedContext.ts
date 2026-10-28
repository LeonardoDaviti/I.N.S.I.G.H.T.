/**
 * The feed context a post page carries in `?ctx=` (spec §F.3), so prev/next keep
 * following the feed order after a reload: `<scope>:<filter>:<cursor>`.
 *
 * - `scope` is the API form: `all`, `folder:<uuid>` or `source:<uuid>`.
 * - `cursor` is the keyset cursor of the feed page that holds the post (empty for
 *   the first page). The post page reloads that page to find its neighbours.
 *
 * Feed cursors use the backend's encoding (urlsafe base64 of "<iso>|<uuid>", no
 * padding), so the client can build one from any item it has loaded.
 */

export type FeedFilter = 'all' | 'unread' | 'later' | 'starred';

export interface FeedContext {
  scope: string;
  filter: FeedFilter;
  cursor: string | null;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CURSOR_RE = /^[A-Za-z0-9_-]+$/;

export function isFeedFilter(value: unknown): value is FeedFilter {
  return value === 'all' || value === 'unread' || value === 'later' || value === 'starred';
}

export function isValidScope(scope: string): boolean {
  if (scope === 'all') return true;
  const [kind, id, ...rest] = scope.split(':');
  return rest.length === 0 && (kind === 'folder' || kind === 'source') && UUID_RE.test(id ?? '');
}

function toBase64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(text: string): string | null {
  if (!text || !CURSOR_RE.test(text)) return null;
  try {
    const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

/** The keyset cursor that positions a feed query at `item` (the backend's FeedCursor.encode). */
export function feedCursorFor(item: { sort_at: string; id: string }): string {
  return toBase64Url(`${item.sort_at}|${item.id}`);
}

export function decodeFeedCursor(cursor: string): { sortAt: string; id: string } | null {
  const raw = fromBase64Url(cursor);
  if (!raw) return null;
  const sep = raw.indexOf('|');
  if (sep <= 0) return null;
  const sortAt = raw.slice(0, sep);
  const id = raw.slice(sep + 1);
  if (Number.isNaN(Date.parse(sortAt)) || !UUID_RE.test(id)) return null;
  return { sortAt, id };
}

export function encodeFeedContext(ctx: FeedContext): string {
  return `${ctx.scope}:${ctx.filter}:${ctx.cursor ?? ''}`;
}

/** Parse `?ctx=`. Anything missing or malformed is null: "no context" (j/k disabled). */
export function decodeFeedContext(raw: string | null | undefined): FeedContext | null {
  if (!raw) return null;
  const parts = raw.split(':');
  if (parts.length < 3) return null;
  const cursor = parts[parts.length - 1];
  const filter = parts[parts.length - 2];
  const scope = parts.slice(0, -2).join(':');
  if (!isFeedFilter(filter) || !isValidScope(scope)) return null;
  if (cursor && !decodeFeedCursor(cursor)) return null;
  return { scope, filter, cursor: cursor || null };
}

export interface ContextEntry {
  id: string;
  /** The cursor of the feed page this post was loaded from (null = the first page). */
  pageCursor: string | null;
}

export interface ContextNeighbors {
  prev: ContextEntry | null;
  next: ContextEntry | null;
  /** At the last loaded id: load the next page with this cursor to find `next`. */
  loadNext: string | null;
  found: boolean;
}

export interface SortedEntry extends ContextEntry {
  /** The feed's sort key: published, else fetched (the backend's COALESCE). */
  sortAt: string;
}

/** Feed order: newest first, ties by id, both descending (the backend's keyset). */
function comesAfter(entry: { id: string; sortAt: string }, current: { id: string; sortAt: string }): boolean {
  const a = Date.parse(entry.sortAt);
  const b = Date.parse(current.sortAt);
  if (a !== b) return a < b;
  return entry.id < current.id;
}

/**
 * Prev/next for `current` by its place in the feed order, whether or not the
 * loaded entries still hold it: a post read under the `unread` filter drops out
 * of a reloaded page, but its neighbours are still the posts around its sort key.
 * After the last loaded entry, `loadNext` names the next page's cursor.
 */
export function neighborsAt(
  entries: readonly SortedEntry[],
  current: { id: string; sortAt: string },
  nextCursor: string | null,
): Omit<ContextNeighbors, 'found'> {
  const others = entries.filter((entry) => entry.id !== current.id);
  // A loaded post's neighbours are the entries around it, in whatever order the list has
  // (Later is oldest saved first, issue 0022); one no longer loaded goes by its sort key.
  const at = entries.findIndex((entry) => entry.id === current.id);
  let index = at >= 0 ? at : others.findIndex((entry) => comesAfter(entry, current));
  if (index < 0) index = others.length;
  const strip = (entry: SortedEntry | undefined): ContextEntry | null => (entry ? { id: entry.id, pageCursor: entry.pageCursor } : null);
  return {
    prev: strip(others[index - 1]),
    next: strip(others[index]),
    loadNext: index === others.length ? nextCursor : null,
  };
}

/** `/` for the main feed, `/read/<kind>/<id>` for a folder or source. */
export function scopePath(scope: string): string {
  if (scope === 'all') return '/';
  const [kind, id] = scope.split(':');
  return `/read/${kind}/${id}`;
}

/** The reader scoped to one folder (a track): where every track link goes (Design Studio D5). */
export function folderReadPath(folderId: string): string {
  return `/read/folder/${encodeURIComponent(folderId)}`;
}

/** The reader scoped to one source: where every "read this source" link goes (issues 0010, 0011). */
export function sourceReadPath(sourceId: string): string { return `/read/source/${encodeURIComponent(sourceId)}`; }

/** Where a source is managed: Sources with its detail sheet open (issue 0003). */
export function sourceSettingsHref(sourceId: string): string {
  return `/settings/sources?source=${encodeURIComponent(sourceId)}`;
}

/** Where a track is managed: Sources scrolled to its group (issue 0003). */
export function trackSettingsHref(folderId: string): string {
  return `/settings/sources?track=${encodeURIComponent(folderId)}`;
}

/** Where a reader scope is managed; null for the main feed. */
export function scopeSettingsHref(scope: string): string | null {
  const [kind, id] = scope.split(':');
  if (kind === 'source' && id) return sourceSettingsHref(id);
  if (kind === 'folder' && id) return trackSettingsHref(id);
  return null;
}

/** The route params of `/read/:scopeKind/:scopeId?` as an API scope; null when invalid. */
export function scopeFromRoute(kind: string | undefined, id: string | undefined): string | null {
  if (!kind) return 'all';
  if (kind === 'all' && !id) return 'all';
  if ((kind === 'folder' || kind === 'source') && id) {
    const scope = `${kind}:${id}`;
    return isValidScope(scope) ? scope : null;
  }
  return null;
}

export function postHref(postId: string, ctx: FeedContext | null): string {
  const base = `/posts/${encodeURIComponent(postId)}`;
  return ctx ? `${base}?ctx=${encodeURIComponent(encodeFeedContext(ctx))}` : base;
}
