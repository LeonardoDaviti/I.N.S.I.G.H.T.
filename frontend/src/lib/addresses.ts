/** An address compared loosely: no scheme, www. or trailing slash, any case. */
export function sameAddress(address: string): string {
  return address.trim().toLowerCase().replace(/^https?:\/\/(www\.)?/, '').replace(/\/+$/, '');
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
