/**
 * The post page's H1. Ingestion stores titles cut at a fixed length with a
 * trailing "…" (GitHub commits, Telegram posts and other title-less items take
 * their title from the text). When the stored title is such a cut and the text
 * starts with it, the H1 shows the text's whole first line instead.
 *
 * Backend note: the cut belongs in the list views only; storing the full first
 * line (and truncating in the feed query) would make this unnecessary.
 */
const ELLIPSIS = /(?:…|\.\.\.)\s*$/;
const MAX_TITLE = 300;

export function displayPostTitle(title: string | null | undefined, content: string | null | undefined): string {
  const stored = (title ?? '').trim();
  if (!stored) return 'Untitled post';
  if (!ELLIPSIS.test(stored)) return stored;
  const prefix = stored.replace(ELLIPSIS, '').trim();
  if (!prefix) return stored;
  const firstLine = (content ?? '').trim().split(/\r?\n/, 1)[0]?.trim() ?? '';
  const normalise = (text: string) => text.replace(/\s+/g, ' ');
  if (!firstLine || !normalise(firstLine).startsWith(normalise(prefix)) || firstLine.length <= prefix.length) return stored;
  if (firstLine.length <= MAX_TITLE) return firstLine;
  return `${Array.from(firstLine).slice(0, MAX_TITLE).join('').trimEnd()}…`;
}
