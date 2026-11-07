import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { POST_ID, baseApi, renderPost, rssPost } from './PostDetailPage.testkit';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import type { FeedStory, PostConnected } from '../services/api';

// Connected on the post page (issue 0125): after the text, before the story; the post never waits on it.

const OTHER = '00000000-0000-4000-8000-0000000000b1';

const connected: PostConnected = {
  success: true,
  earlier: [{ post_id: OTHER, url: 'https://writer.test/part-one', source: 'A writer', date: '2026-10-20T08:00:00+00:00',
    title: 'Part one', same_source: true, reason: 'Part one', reason_kind: 'title' }],
  later: [],
  outside: [],
  more: { earlier: 0, later: 0, outside: 0 },
};

const story: FeedStory = {
  id: OTHER, voices: 2, first: OTHER,
  sources: [{ id: 's1', name: 'A writer' }, { id: 's2', name: 'Another writer' }],
  posts: [{ id: OTHER, title: 'Part one', url: 'https://writer.test/part-one', source_id: 's1', source_display_name: 'A writer',
    platform: 'rss', sort_at: '2026-10-20T08:00:00+00:00', published_at: '2026-10-20T08:00:00+00:00', read_at: null, role: 'report' }],
};

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('PostDetailPage connected (issue 0125)', () => {
  it('comes after the text and before the story', async () => {
    const get = vi.fn().mockResolvedValue(connected);
    renderPost(baseApi(rssPost({ story }), { getPostConnected: get }));
    const block = await screen.findByRole('region', { name: 'Connected' });
    expect(get).toHaveBeenCalledWith(POST_ID, false);
    const article = screen.getByRole('article', { name: 'Post content' });
    const covered = screen.getByRole('region', { name: 'Covered by' });
    expect(article.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(block.compareDocumentPosition(covered) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('the post shows while Connected is still loading', async () => {
    renderPost(baseApi(rssPost(), { getPostConnected: vi.fn(() => new Promise(() => {})) }));
    expect(await screen.findByRole('article', { name: 'Post content' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Connected' })).toBeNull();
  });
});
