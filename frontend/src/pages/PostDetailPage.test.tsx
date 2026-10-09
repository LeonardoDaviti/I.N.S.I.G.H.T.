import { describe, expect, it, vi } from 'vitest';
import { render as rtlRender, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import PostDetailPage, { displaySourceName } from './PostDetailPage';
import MarkdownRenderer, { normalizeRendererContent } from '../components/ui/MarkdownRenderer';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api, Post } from '../services/api';

const POST_ID = '7dbe33ac-ddda-429f-a8a2-d51a05f5ecaf';

function rssPost(overrides: Partial<Post> = {}): Post {
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
    topics: [],
    metadata: {},
    ...overrides,
  };
}

function youtubePost(): Post {
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

function baseApi(post: Post, methods: Partial<Record<keyof Api, unknown>> = {}) {
  return makeFakeApi({
    getPostDetail: vi.fn().mockResolvedValue({
      success: true,
      post,
      notes: null,
      summary: null,
      summary_references: [],
      highlights: [],
      reader_state: { post_id: POST_ID, is_favorited: false, open_count: 2, total_read_seconds: 252 },
    }),
    getPostTimeline: vi.fn().mockResolvedValue({ success: true, primary_story: null, story: null, timeline: null, related_candidates: [] }),
    recordPostOpen: vi.fn().mockResolvedValue({ success: true }),
    recordPostReadingSession: vi.fn().mockResolvedValue({ success: true }),
    getYouTubeWatchProgress: vi.fn().mockResolvedValue({ success: true, progress: null }),
    ...methods,
  });
}

function render(api: Api) {
  return renderWithProviders(
    <Routes>
      <Route path="/posts/:postId" element={<PostDetailPage />} />
    </Routes>,
    { api, route: `/posts/${POST_ID}` },
  );
}

describe('PostDetailPage header', () => {
  it('shows the source host, platform, date, title and the original link', async () => {
    render(baseApi(rssPost()));
    const heading = await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    const header = heading.closest('header')!;
    expect(within(header).getByText('simonwillison.net')).toBeInTheDocument();
    expect(within(header).getByText('rss')).toBeInTheDocument();
    expect(header.querySelector('time')).toHaveAttribute('dateTime', '2026-09-27T23:54:15+00:00');
    const original = within(header).getByRole('link', { name: /open original/i });
    expect(original).toHaveAttribute('href', 'https://simonwillison.net/2026/Sep/27/2026-in-llms-so-far/');
    expect(original).toHaveAttribute('target', '_blank');
  });

  it('renders indented feed HTML as paragraphs, not as a code block', async () => {
    render(baseApi(rssPost()));
    const article = await screen.findByRole('article', { name: 'Post content' });
    expect(article.querySelector('pre')).toBeNull();
    expect(within(article).getByText('On Friday I gave the closing keynote.').tagName).toBe('P');
  });

  it('copies the post text and says so', async () => {
    const user = userEvent.setup();
    render(baseApi(rssPost()));
    await user.click(await screen.findByRole('button', { name: 'Copy text' }));
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
    await expect(navigator.clipboard.readText()).resolves.toBe(
      'On Friday I gave the closing keynote. Agents shipped everywhere this year.',
    );
  });

  it('stars the post and reflects it with aria-pressed', async () => {
    const user = userEvent.setup();
    const togglePostFavorite = vi.fn().mockResolvedValue({ success: true, favorited: true });
    render(baseApi(rssPost(), { togglePostFavorite }));
    await user.click(await screen.findByRole('button', { name: 'Star' }));
    expect(togglePostFavorite).toHaveBeenCalledWith(POST_ID, true);
    expect(await screen.findByRole('button', { name: 'Starred' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows a request error as a dismissible notice', async () => {
    const user = userEvent.setup();
    const getPostSummary = vi.fn().mockResolvedValue({ success: false, error: 'LLM quota exhausted' });
    render(baseApi(rssPost(), { getPostSummary }));
    await user.click(await screen.findByRole('button', { name: 'Generate summary' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('LLM quota exhausted');
    await user.click(within(alert).getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('PostDetailPage intelligence inspector', () => {
  it('stays closed and unfetched until Inspect opens it in a sheet', async () => {
    const user = userEvent.setup();
    const getPostEvidence = vi.fn().mockResolvedValue({
      success: true,
      evidence: { post: { url_host: 'simonwillison.net', normalized_url: 'https://simonwillison.net/x' }, artifacts: [], relations: { outgoing: [], incoming: [] } },
    });
    render(baseApi(rssPost(), { getPostEvidence }));
    await screen.findByRole('heading', { level: 1 });
    expect(getPostEvidence).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Inspect' }));
    const sheet = await screen.findByRole('dialog', { name: 'Post intelligence' });
    expect(getPostEvidence).toHaveBeenCalledWith(POST_ID);
    expect(await within(sheet).findByText('https://simonwillison.net/x')).toBeInTheDocument();
    expect(within(sheet).getByRole('tab', { name: 'evidence' })).toHaveAttribute('aria-selected', 'true');
  });
});

describe('PostDetailPage highlights', () => {
  it('marks highlights with a neutral tint and underlines the ones the summary used', async () => {
    const api = makeFakeApi({
      getPostDetail: vi.fn().mockResolvedValue({
        success: true,
        post: rssPost(),
        summary: { summary_markdown: 'Short version.', model: 'test-model', one_sentence_takeaway: 'Agents won the year.' },
        summary_references: [{ highlight_id: 'h2' }],
        highlights: [
          { id: 'h1', highlight_text: 'closing keynote' },
          { id: 'h2', highlight_text: 'Agents shipped everywhere' },
        ],
        reader_state: null,
      }),
      getPostTimeline: vi.fn().mockResolvedValue({ success: true, timeline: null, related_candidates: [] }),
      recordPostOpen: vi.fn().mockResolvedValue({ success: true }),
      recordPostReadingSession: vi.fn().mockResolvedValue({ success: true }),
    });
    render(api);
    const article = await screen.findByRole('article', { name: 'Post content' });
    const marks = article.querySelectorAll('mark');
    expect(Array.from(marks, (mark) => mark.textContent)).toEqual(['closing keynote', 'Agents shipped everywhere']);
    expect(marks[0]).not.toHaveAttribute('data-used-in-summary');
    expect(marks[1]).toHaveAttribute('data-used-in-summary', 'true');
    for (const mark of marks) {
      expect(mark.className).not.toMatch(/yellow|rgba/);
    }
    // The summary is open because it exists, with its takeaway first.
    expect(screen.getByText('Agents won the year.')).toBeVisible();
  });
});

describe('PostDetailPage YouTube watch mode', () => {
  it('embeds the video, lists transcript sections and saves the chosen progress', async () => {
    const user = userEvent.setup();
    const saveYouTubeWatchProgress = vi.fn().mockResolvedValue({
      success: true,
      progress: { progress_seconds: 0, progress_percent: 0 },
    });
    render(baseApi(youtubePost(), { saveYouTubeWatchProgress }));

    const iframe = await screen.findByTitle('Some OpenVPN Connections Broke on Linux Mint 22.3');
    expect(iframe).toHaveAttribute('src', 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ');
    // The channel title replaces the channel id in the header.
    expect(screen.getByText('Switched to Linux')).toBeInTheDocument();

    const transcript = screen.getByRole('article', { name: 'Transcript' });
    expect(within(transcript).getAllByRole('heading', { level: 3 })).toHaveLength(2);

    const setButtons = within(transcript).getAllByRole('button', { name: 'Set progress here' });
    await user.click(setButtons[1]);
    expect(screen.getByText(/\/ 10:00$/)).toHaveTextContent(/^\d+:\d\d \/ 10:00$/);
    expect(screen.queryByText('0:00 / 10:00')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Save progress' }));
    expect(saveYouTubeWatchProgress).toHaveBeenCalledWith(
      'dQw4w9WgXcQ',
      expect.objectContaining({ progressSeconds: expect.any(Number), completed: false }),
    );
    const saved = saveYouTubeWatchProgress.mock.calls[0][1].progressSeconds;
    expect(saved).toBeGreaterThan(0);
  });
});

describe('displaySourceName', () => {
  it('prefers the YouTube channel title, else the feed host, else the label', () => {
    expect(displaySourceName({ source: 'UCx', platform: 'youtube', metadata: { channel_title: 'Switched to Linux' } })).toBe('Switched to Linux');
    expect(displaySourceName({ source: 'https://www.example.com/feed.xml', platform: 'rss' })).toBe('example.com');
    expect(displaySourceName({ source: 'x', source_display_name: 'Simon Willison', platform: 'rss' })).toBe('Simon Willison');
    expect(displaySourceName({ source: '', platform: 'rss' })).toBe('Unknown source');
  });
});

describe('MarkdownRenderer', () => {
  it('keeps inline code inline and fenced code in a scrollable pre', () => {
    const { container } = rtlRender(<MarkdownRenderer content={'Run `npm test` now.\n\n```\nconst a = 1;\n```'} />);
    const inline = within(container).getByText('npm test');
    expect(inline.tagName).toBe('CODE');
    expect(inline.closest('pre')).toBeNull();
    expect(inline.closest('p')).not.toBeNull();
    const pre = container.querySelector('pre')!;
    expect(pre.className).toContain('overflow-x-auto');
    expect(pre.textContent).toContain('const a = 1;');
  });

  it('wraps a <pre> of bare prose (GitHub commit bodies) instead of cutting it off', () => {
    const { container } = rtlRender(<MarkdownRenderer content={"<pre style='white-space:pre-wrap;width:81ex'>Update the skill (#1930)\n\n* bump every example</pre>"} />);
    const pre = container.querySelector('pre')!;
    expect(pre.className).toContain('whitespace-pre-wrap');
    expect(pre.className).not.toContain('overflow-x-auto');
    expect(pre.getAttribute('style')).toBeNull();
  });

  it('holds a frame for an unsized image until it loads', () => {
    const { container } = rtlRender(<MarkdownRenderer content={'<p>a</p><img src="/x.webp" alt="x"><img src="/y.webp" alt="y" width="400" height="300">'} />);
    const [unsized, sized] = Array.from(container.querySelectorAll('img'));
    expect(unsized.className).toContain('aspect-[16/10]');
    expect(sized.className).not.toContain('aspect-[16/10]');
    expect(sized.getAttribute('width')).toBe('400');
  });

  it('lets each paragraph take its own direction, so Arabic or Hebrew reads right to left', () => {
    const { container } = rtlRender(<MarkdownRenderer content={'<p>hello</p><p dir="rtl">مرحبا بالعالم</p>'} />);
    for (const paragraph of container.querySelectorAll('p')) {
      expect(paragraph).toHaveAttribute('dir', 'auto');
    }
  });

  it('dedents indented HTML so markdown does not read it as code', () => {
    expect(normalizeRendererContent('\n    <p>Hello</p>\n    <p>World</p>')).toBe('\n<p>Hello</p>\n<p>World</p>');
    // Plain markdown with an indented code block is left alone.
    expect(normalizeRendererContent('Text\n\n    code')).toBe('Text\n\n    code');
  });
});
