/**
 * HTML read where nothing in it can run. A post's HTML is the feed's: as innerHTML it would load its images and
 * fire their onerror handlers, even on an element never shown. A DOMParser document has no window, so nothing
 * runs or loads. Every read of HTML for its text goes through here, never through the page's own document.
 */

function inertDocument(html: string): Document {
  return new DOMParser().parseFromString(html, 'text/html');
}

/** The text of an HTML fragment, read without running or loading anything in it. */
export function htmlText(html: string): string {
  if (!html || typeof DOMParser === 'undefined') return '';
  return inertDocument(html).body.textContent ?? '';
}

/** "&lt;p&gt; &amp;" -> "<p> &": entities decoded and tags kept as text, as a textarea reads them, in an inert document. */
export function decodeEntities(input: string): string {
  if (typeof DOMParser === 'undefined') {
    return input
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, '&');
  }
  const textarea = inertDocument('').createElement('textarea');
  textarea.innerHTML = input;
  return textarea.value;
}
