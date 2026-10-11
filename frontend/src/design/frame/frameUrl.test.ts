import { describe, expect, it } from 'vitest';

import { frameUrl, parseFrameLocation, prototypeFrameUrl } from './frameUrl';

describe('the frame route', () => {
  it('reads a page and state, with dark and fixtures by default', () => {
    expect(parseFrameLocation('/design/frame/post/long-title', '')).toEqual({ page: 'post', state: 'long-title', theme: 'dark', data: 'fixtures' });
  });

  it('reads a prototype path: /design/frame/prototype/:id/:state', () => {
    expect(parseFrameLocation('/design/frame/prototype/2026-10-10-title-wrap/article', '?theme=light')).toEqual({
      page: '', prototype: '2026-10-10-title-wrap', state: 'article', theme: 'light', data: 'fixtures',
    });
  });

  it('builds both kinds of address, and reads them back', () => {
    const url = prototypeFrameUrl('2026-10-10-title-wrap', 'long-title', { theme: 'light' });
    expect(url).toBe('/design/frame/prototype/2026-10-10-title-wrap/long-title?theme=light&data=fixtures');
    const [path, search] = url.split('?');
    expect(parseFrameLocation(path, `?${search}`)?.prototype).toBe('2026-10-10-title-wrap');
    expect(frameUrl('post', 'article')).toBe('/design/frame/post/article?theme=dark&data=fixtures');
  });

  it('carries the walk flag on either kind of address', () => {
    const page = frameUrl('reader', 'normal', { walk: true });
    expect(page).toBe('/design/frame/reader/normal?theme=dark&data=fixtures&walk=1');
    const [path, search] = page.split('?');
    expect(parseFrameLocation(path, `?${search}`)?.walk).toBe(true);
    expect(prototypeFrameUrl('2026-10-10-title-wrap', 'long-title', { walk: true })).toMatch(/&walk=1$/);
  });
});
