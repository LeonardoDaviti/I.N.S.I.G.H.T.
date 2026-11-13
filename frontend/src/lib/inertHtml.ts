/**
 * HTML read where nothing in it can run (issue 0187). A post's HTML is the feed's: setting it as an element's
 * innerHTML in the page loads its images and fires their onerror handlers, even on an element never shown.
 * A document made by DOMParser has no window: its scripts don't run, its images don't load, no handler fires.
 * Every read of HTML for its text goes through here, never through the page's own document.
 */

function inertDocument(html: string): Document {
  return new DOMParser().parseFromString(html, 'text/html');
}

/** The text of an HTML fragment, read without running or loading anything in it. */
export function htmlText(html: string): string {
  if (!html || typeof DOMParser === 'undefined') return '';
  return inertDocument(html).body.textContent ?? '';
}

/** "&lt;p&gt; &amp;" -> "<p> &": entities decoded and tags kept as text, as a textarea reads them, in an inert
 * document (a textarea's content is never markup, and its document runs nothing either way). */
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
