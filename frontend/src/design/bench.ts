/**
 * Bench mode's address (verdict C): what is compared lives in the URL, so a
 * comparison can be linked, reloaded and screenshotted (D9).
 */

/** Bench opened on a subject: a prototype id or a page doc's name. */
export function benchHref(subject: string): string {
  return `/design?${new URLSearchParams({ mode: 'bench', subject }).toString()}`;
}
