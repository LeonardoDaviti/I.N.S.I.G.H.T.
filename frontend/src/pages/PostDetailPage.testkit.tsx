import { vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import PostDetailPage from './PostDetailPage';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api, Post } from '../services/api';

/** Shared fixtures for the post page tests. */
export const POST_ID = '7dbe33ac-ddda-429f-a8a2-d51a05f5ecaf';

export function rssPost(overrides: Partial<Post> = {}): Post {
  return {
    id: POST_ID,
    title: '2026 in LLMs (so far)',
    source: 'https://simonwillison.net/atom/everything/',
    source_display_name: 'https://simonwillison.net/atom/everything/',
    platform: 'rss',
    url: 'https://simonwillison.net/2026/Sep/27/2026-in-llms-so-far/',
    published_at: '2026-09-27T23:54:15+00:00',
    content: 'On Friday I gave the closing keynote. Agents shipped everywhere this year.',
    // Feed HTML arrives indented; four spaces must not turn it into a code block.
    content_html: '\n    <p>On Friday I gave the closing keynote.</p>\n    <p>Agents shipped everywhere this year.</p>',
    categories: ['ai', 'llms'],
    metadata: {},
    ...overrides,
  };
}

export function youtubePost(): Post {
  return {
    id: POST_ID,
    title: 'Some OpenVPN Connections Broke on Linux Mint 22.3',
    source: 'UCoryWpk4QVYKFCJul9KBdyw',
    platform: 'youtube',
    external_id: 'dQw4w9WgXcQ',
    url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    published_at: '2026-09-28T04:00:00+00:00',
    content: 'Welcome back to the channel.\nToday we fix a VPN.\n\nFirst open the network manager.\nThen restart it.',
    metadata: { channel_title: 'Switched to Linux', duration_seconds: 600, transcript_source: 'automatic_captions:en' },
  };
}

export function baseApi(post: Post, methods: Partial<Record<keyof Api, unknown>> = {}) {
  return makeFakeApi({
    getPostDetail: vi.fn().mockResolvedValue({
      success: true,
      post,
      reader_state: { post_id: POST_ID, is_favorited: false, open_count: 2, total_read_seconds: 252 },
    }),
    recordPostOpen: vi.fn().mockResolvedValue({ success: true }),
    recordPostReadingSession: vi.fn().mockResolvedValue({ success: true }),
    getYouTubeWatchProgress: vi.fn().mockResolvedValue({ success: true, progress: null }),
    ...methods,
  });
}

export function renderPost(api: Api) {
  return renderWithProviders(
    <Routes>
      <Route path="/posts/:postId" element={<PostDetailPage />} />
    </Routes>,
    { api, route: `/posts/${POST_ID}` },
  );
}

