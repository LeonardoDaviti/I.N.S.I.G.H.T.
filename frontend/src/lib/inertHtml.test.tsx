import { afterEach, describe, expect, it, vi } from 'vitest';
import { decodeEntities, htmlText } from './inertHtml';

// Issue 0187: a post's HTML is the feed's. Reading its text must never run or load anything in it.
const HOSTILE = '<p>Hello <b>world</b></p><img src="x" onerror="window.__xss = 1">'
  + '<script>window.__xss = 2</script><svg onload="window.__xss = 3"></svg>'
  + '<iframe srcdoc="<script>parent.__xss = 4</script>"></iframe>';

declare global {
  interface Window { __xss?: number }
}

afterEach(() => {
  vi.restoreAllMocks();
  delete window.__xss;
});

describe('htmlText', () => {
  it('reads the text', () => {
    expect(htmlText('<p>Hello <b>world</b> &amp; more</p>')).toBe('Hello world & more');
    expect(htmlText('')).toBe('');
  });

  it('never runs a handler or a script, and never touches the page', async () => {
    const created = vi.spyOn(document, 'createElement');
    const parse = vi.spyOn(DOMParser.prototype, 'parseFromString');
    expect(htmlText(HOSTILE)).toContain('Hello world');
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(window.__xss).toBeUndefined();
    expect(created).not.toHaveBeenCalled();
    // parsed in a document with no window: nothing in it can run or load
    expect(parse).toHaveBeenCalledTimes(1);
    expect((parse.mock.results[0].value as Document).defaultView).toBeNull();
  });
});

describe('decodeEntities', () => {
  it('decodes entities and keeps tags as text', () => {
    expect(decodeEntities('&lt;p&gt;A &amp; B&lt;/p&gt; &quot;q&quot; &#39;s')).toBe('<p>A & B</p> "q" \'s');
  });

  it('never runs what it decodes', async () => {
    const created = vi.spyOn(document, 'createElement');
    expect(decodeEntities(`</textarea>${HOSTILE}`)).toContain('<img src="x"');
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(window.__xss).toBeUndefined();
    expect(created).not.toHaveBeenCalled();
  });
});
