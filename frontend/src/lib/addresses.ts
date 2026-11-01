/** An address's publication, as the backend's publication_of (issue 0071: one definition): its host
 * without www. ("example.com"), with or without its scheme; '' when it has none. */
export function publicationOf(address: string): string {
  try {
    return new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(address) ? address : `https://${address}`).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

/** An address without its scheme and www. ("example.com/a"): a page's name when it has no title. */
export function bareAddress(address: string): string {
  return address.replace(/^https?:\/\/(www\.)?/i, '');
}

/** An address compared loosely: no scheme, www. or trailing slash, any case. */
export function sameAddress(address: string): string {
  return bareAddress(address.trim().toLowerCase()).replace(/\/+$/, '');
}

/** An address as a line shows it: no scheme. */
export function shortAddress(address: string): string {
  return address.replace(/^https?:\/\//, '');
}

/** An address as a source's name: no scheme or trailing slash ("stripe.com"). */
export function siteName(address: string): string {
  return shortAddress(address.trim()).replace(/\/+$/, '');
}

/** A followed page is read as an address: it needs its scheme. */
export function withScheme(address: string): string {
  return /^https?:\/\//i.test(address) ? address : `https://${address}`;
}

/** The warning on following a site's home page (issue 0041). */
export const HOMEPAGE_WARNING = 'This is the site\'s homepage: it may pick up product pages, not articles.';
