/**
 * The reader rail's source filter: case- and diacritic-insensitive, every word
 * of the query must appear in one of the source's names, its URL or its kind.
 *
 *   "kaitchup"   -> The Kaitchup
 *   "CAFE"       -> Café Tech
 *   "github rel" -> anthropics/skills releases (github.com/... + "releases")
 */
export interface SearchableSource {
  /** The stored display name (may be a URL). */
  name: string;
  /** The readable name shown in the rail (sourceLabel of `name`). */
  label: string;
  url?: string | null;
  kind?: string | null;
  platform?: string | null;
}

/** Lowercase, strip diacritics, and turn `_`/`-` runs into spaces. */
export function foldForSearch(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .toLowerCase()
    .replace(/[_\s]+/g, ' ')
    .trim();
}

export function queryWords(query: string): string[] {
  return foldForSearch(query).split(' ').filter(Boolean);
}

export function matchesSource(source: SearchableSource, words: readonly string[]): boolean {
  if (!words.length) return true;
  const haystack = foldForSearch([source.label, source.name, source.url, source.kind, source.platform].filter(Boolean).join(' '));
  return words.every((word) => haystack.includes(word));
}
