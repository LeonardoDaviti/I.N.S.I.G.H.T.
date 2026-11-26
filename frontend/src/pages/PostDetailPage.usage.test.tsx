import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { baseApi, POST_ID, renderPost, rssPost } from './PostDetailPage.testkit';

// Your reading on the post page: the session's active seconds and depth, and the original opened.

afterEach(() => {
  vi.restoreAllMocks();
});

describe('PostDetailPage reading usage', () => {
  it('records the original opened from the band, once a click', async () => {
    const user = userEvent.setup();
    const post = rssPost();
    const api = baseApi(post, { recordPostSourceOpen: vi.fn().mockResolvedValue({ success: true }) });
    renderPost(api);
    await screen.findByRole('heading', { level: 1 });
    await user.click(await screen.findByRole('link', { name: 'Open original' }));
    await waitFor(() => expect(api.recordPostSourceOpen).toHaveBeenCalledWith(POST_ID, post.url));
    expect(api.recordPostSourceOpen).toHaveBeenCalledTimes(1);
  });

  it('sends active seconds and the depth reached with the reading session', async () => {
    vi.spyOn(document, 'hasFocus').mockReturnValue(true);
    // the article body: its top 100px down a 768px viewport, 1336px tall -> half read
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(
      { top: 100, height: 1336, bottom: 1436, left: 0, right: 0, width: 0, x: 0, y: 100, toJSON: () => ({}) } as DOMRect);
    const api = baseApi(rssPost());
    const { unmount } = renderPost(api);
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(api.recordPostOpen).toHaveBeenCalled());

    // five minutes on, the tab left alone: then a key, and the post is left
    const later = Date.now() + 300_000;
    vi.spyOn(Date, 'now').mockReturnValue(later);
    window.dispatchEvent(new KeyboardEvent('keydown'));
    unmount();

    expect(api.recordPostReadingSession).toHaveBeenCalledTimes(1);
    const [id, seconds, , measured] = vi.mocked(api.recordPostReadingSession).mock.calls[0];
    expect(id).toBe(POST_ID);
    expect(seconds).toBeGreaterThanOrEqual(299);
    // idle for the minutes between: only the capped last step after the key counts, never the five minutes
    expect(measured).toEqual({ activeSeconds: 5, depth: 0.5 });
  });
});
