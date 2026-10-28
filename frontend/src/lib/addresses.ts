/** An address compared loosely: no scheme, www. or trailing slash, any case. */
export function sameAddress(address: string): string {
  return address.trim().toLowerCase().replace(/^https?:\/\/(www\.)?/, '').replace(/\/+$/, '');
}

/** An address as a line shows it: no scheme. */
export function shortAddress(address: string): string {
  return address.replace(/^https?:\/\//, '');
}
