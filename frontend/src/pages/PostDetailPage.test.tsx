import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render as rtlRender, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';
import { POST_ID, baseApi, renderPost as render, rssPost, youtubePost } from './PostDetailPage.testkit';

import PostDetailPage from './PostDetailPage';
import { postSourceName as displaySourceName } from '../lib/sourceLabel';
import MarkdownRenderer, { normalizeRendererContent } from '../components/ui/MarkdownRenderer';
import { makeFakeApi } from '../test/fakeApi';
import { makeTestQueryClient, renderWithProviders } from '../test/render';
import { postKey } from '../hooks/usePost';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import { feedItem, feedPage } from '../components/reader/fixtures';
import type { Api, Post } from '../services/api';

describe('PostDetailPage header', () => {
  it('shows the source host, date, title and the original link, and no platform (issue 0027)', async () => {
    render(baseApi(rssPost()));
    const heading = await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    const header = heading.closest('header')!;
    expect(within(header).getByText('simonwillison.net')).toBeInTheDocument();
    expect(within(header).queryByText('rss')).toBeNull();
    expect(header.querySelector('time')).toHaveAttribute('dateTime', '2026-09-27T23:54:15+00:00');
    const original = within(header).getByRole('link', { name: /open original/i });
    expect(original).toHaveAttribute('href', 'https://simonwillison.net/2026/Sep/27/2026-in-llms-so-far/');
    expect(original).toHaveAttribute('target', '_blank');
  });

  it('the source name reads the source; settings beside it opens it in Sources (issue 0010)', async () => {
    render(baseApi(rssPost({ source_id: 'src-1' })));
    const heading = await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    const header = heading.closest('header')!;
    expect(within(header).getByRole('link', { name: 'simonwillison.net' })).toHaveAttribute('href', '/read/source/src-1');
    expect(within(header).getByRole('link', { name: 'settings' })).toHaveAttribute('href', '/settings/sources?source=src-1');
  });

  it('a post with no source id keeps its source name as plain text', async () => {
    render(baseApi(rssPost({ source_id: undefined })));
    const heading = await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    expect(within(heading.closest('header')!).queryByRole('link', { name: 'simonwillison.net' })).toBeNull();
  });

  it('shows the API title as given and names the tab after it (issue 0009)', async () => {
    const content = 'Our new model is out today and it is better at everything. And more besides.';
    render(baseApi(rssPost({ title: 'Our new model is out today and it is better at everything.', content, content_html: undefined })));
    await screen.findByRole('heading', { level: 1, name: 'Our new model is out today and it is better at everything.' });
    expect(document.title).toBe('Our new model is out today and it is better at everything. · INSIGHT');
    expect(within(screen.getByRole('article', { name: 'Post content' })).getByText(content)).toBeInTheDocument();
  });

  it('does not repeat a body that is exactly the title', async () => {
    render(baseApi(rssPost({ title: 'Shipping today.', content: 'Shipping today.', content_html: undefined })));
    await screen.findByRole('heading', { level: 1, name: 'Shipping today.' });
    expect(screen.getByRole('article', { name: 'Post content' })).toHaveTextContent(/^$/);
  });

  it('shows a plain body\'s literal tags as text, keeping its links and line breaks', async () => {
    // Stored plain text is decoded already: "<details>" here is what the author wrote.
    const content = 'Wrap spoilers in <details> and <b>.\nMore at https://example.com/a?x=1&y=2';
    render(baseApi(rssPost({ title: 'Spoilers', content, content_html: undefined })));
    const article = await screen.findByRole('article', { name: 'Post content' });
    expect(article.querySelector('details, b')).toBeNull();
    expect(article.querySelector('p')?.textContent).toBe(content);
    expect(within(article).getByRole('link', { name: 'https://example.com/a?x=1&y=2' }))
      .toHaveAttribute('href', 'https://example.com/a?x=1&y=2');
  });

  it('lets the title fill the reading column: pretty wrapping, not balanced into two short lines', async () => {
    render(baseApi(rssPost()));
    const heading = await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    expect(heading.className).toContain('text-pretty');
    expect(heading.className).not.toContain('text-balance');
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
    const star = await screen.findByRole('button', { name: 'Star' });
    expect(star).toHaveAttribute('aria-pressed', 'false');
    await user.click(star);
    expect(togglePostFavorite).toHaveBeenCalledWith(POST_ID, true);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Star' })).toHaveAttribute('aria-pressed', 'true'));
  });

});

describe('PostDetailPage reading view', () => {
  it('puts open original, star and copy as icon-only buttons in the title block, and no Inspect', async () => {
    render(baseApi(rssPost()));
    const heading = await screen.findByRole('heading', { level: 1 });
    const header = heading.closest('header')!;
    const actions = within(header).getByRole('group', { name: 'Post actions' });
    const controls = Array.from(actions.querySelectorAll('a, button'));
    expect(controls.map((control) => control.getAttribute('aria-label'))).toEqual(['Open original', 'Star', 'Copy text']);
    for (const control of controls) {
      // Icon only: the name comes from aria-label, no visible words.
      expect(control.textContent).toBe('');
      expect(control.querySelector('svg')).not.toBeNull();
    }
    // The actions sit on the line above the title, so they come before it in the header.
    expect(actions.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Inspect' })).toBeNull();
    expect(screen.queryByText('Open original')).toBeNull();
  });

  it('links the discussion when the feed names one (Hacker News)', async () => {
    render(baseApi(rssPost({ metadata: { comments_url: 'https://news.ycombinator.com/item?id=1' } })));
    const link = await screen.findByRole('link', { name: 'Open discussion' });
    expect(link).toHaveAttribute('href', 'https://news.ycombinator.com/item?id=1');
    const actions = screen.getByRole('group', { name: 'Post actions' });
    const labels = Array.from(actions.querySelectorAll('a, button')).map((control) => control.getAttribute('aria-label'));
    expect(labels).toEqual(['Open original', 'Open discussion', 'Star', 'Copy text']);
  });

  it('a Reddit post offers no Fetch comments (Reddit refuses it); comments stored with it still show', async () => {
    const { unmount } = render(baseApi(rssPost({ platform: 'reddit' })));
    await screen.findByRole('heading', { name: '2026 in LLMs (so far)' });
    expect(screen.queryByRole('button', { name: /comments/i })).toBeNull();
    expect(screen.queryByText('Discussion')).toBeNull();
    unmount();
    render(baseApi(rssPost({ platform: 'reddit', metadata: { reddit_discussion: { comments: [{ id: 'c1', author: 'ann', body: 'Nice post', score: 3 }] } } })));
    expect(await screen.findByText('Nice post')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /comments/i })).toBeNull();
  });

  it('shows a tooltip naming the action on hover', async () => {
    const user = userEvent.setup();
    render(baseApi(rssPost()));
    await user.hover(await screen.findByRole('button', { name: 'Copy text' }));
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Copy text');
  });

  it('stars with the s key as well as the button', async () => {
    const user = userEvent.setup();
    const togglePostFavorite = vi.fn().mockResolvedValue({ success: true, favorited: true });
    render(baseApi(rssPost(), { togglePostFavorite }));
    await screen.findByRole('heading', { level: 1 });
    await user.keyboard('s');
    expect(togglePostFavorite).toHaveBeenCalledWith(POST_ID, true);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Star' })).toHaveAttribute('aria-pressed', 'true'));
  });

  it('renders no summary, inspector, notes, chat, story or tags, even from an old response that still carries them', async () => {
    const api = baseApi(rssPost());
    const old = {
      success: true,
      post: { ...rssPost(), topics: [{ id: 't1', title: 'A briefing topic', date: '2026-09-27' }] },
      summary: { summary_markdown: 'Short version.', model: 'm', one_sentence_takeaway: 'Agents won the year.' },
      summary_references: [],
      highlights: [{ id: 'h1', highlight_text: 'closing keynote' }],
      reader_state: null,
    };
    vi.mocked(api.getPostDetail).mockResolvedValue(old);
    render(api);
    const article = await screen.findByRole('article', { name: 'Post content' });
    expect(screen.queryByText('Summary')).toBeNull();
    expect(screen.queryByText('not generated yet')).toBeNull();
    expect(screen.queryByText('Agents won the year.')).toBeNull();
    expect(screen.queryByText('Story')).toBeNull();
    expect(screen.queryByText('Tags and topics')).toBeNull();
    expect(screen.queryByRole('complementary', { name: 'Notes and chat' })).toBeNull();
    expect(screen.queryByRole('tab')).toBeNull();
    expect(article.querySelector('mark')).toBeNull();
    // Nothing beside the text: the page is one column.
    expect(article.closest('.grid')?.children).toHaveLength(1);
  });
});

describe('PostDetailPage images', () => {
  const IMAGES = [
    { url: 'https://static.example.com/hero.webp' },
    { url: 'https://static.example.com/inline.webp' },
    { url: 'https://static.example.com/second.png' },
  ];

  it('shows the first image under the title, the rest after the text, skipping the ones the body shows', async () => {
    const content_html = '<p>Look:</p><p><img src="https://static.example.com/inline.webp" alt="inline"></p>';
    render(baseApi(rssPost({ content_html, images: IMAGES } as Partial<Post>)));
    const heading = await screen.findByRole('heading', { level: 1 });
    const figures = Array.from(document.querySelectorAll('[data-post-image]'));
    // Every image loads through /api/media (issue 0006), naming its post and its original URL.
    const proxied = (img: Element) => new URL(img.getAttribute('src')!, 'http://insight.test');
    const sources = figures.map((figure) => proxied(figure.querySelector('img')!));
    expect(sources.every((src) => src.pathname === '/api/media')).toBe(true);
    expect(sources.map((src) => src.searchParams.get('url'))).toEqual([
      'https://static.example.com/hero.webp',
      'https://static.example.com/second.png',
    ]);
    const article = screen.getByRole('article', { name: 'Post content' });
    expect(proxied(article.querySelector('img')!).searchParams.get('url')).toBe('https://static.example.com/inline.webp');
    expect(heading.compareDocumentPosition(figures[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(figures[0].compareDocumentPosition(article) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(article.compareDocumentPosition(figures[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The body keeps its own image, once.
    expect(article.querySelectorAll('img')).toHaveLength(1);
    for (const figure of figures) {
      const img = figure.querySelector('img')!;
      // Reserved space before load (no layout shift), lazy, and no grey filter.
      expect((figure as HTMLElement).style.aspectRatio).toBe('16 / 10');
      expect(img).toHaveAttribute('width');
      expect(img).toHaveAttribute('height');
      expect(img).toHaveAttribute('loading', 'lazy');
      expect(img.className).not.toMatch(/grayscale/);
    }
  });

  it('drops an image whose link is dead', async () => {
    render(baseApi(rssPost({ images: [IMAGES[0]] } as Partial<Post>)));
    await screen.findByRole('heading', { level: 1 });
    const img = document.querySelector('[data-post-image] img')!;
    fireEvent.error(img);
    await waitFor(() => expect(document.querySelector('[data-post-image]')).toBeNull());
  });

  it('a YouTube post shows the player from the video field and no image hero', async () => {
    const post = { ...youtubePost(), external_id: null, url: 'https://example.com/not-youtube', images: [IMAGES[0]], video: { provider: 'youtube', id: 'CIzgNnWNzII' } };
    render(baseApi(post as Post));
    const iframe = await screen.findByTitle(post.title!);
    expect(iframe).toHaveAttribute('src', 'https://www.youtube-nocookie.com/embed/CIzgNnWNzII');
    expect(screen.queryByRole('button', { name: /watch guide/i })).toBeNull();
    const figures = document.querySelectorAll('[data-post-image]');
    expect(figures).toHaveLength(1);
    const transcript = screen.getByRole('article', { name: 'Transcript' });
    expect(transcript.compareDocumentPosition(figures[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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

  it('renders #### Codex voice mode as an h4 subheading, not body text', () => {
    const { container } = rtlRender(<MarkdownRenderer content={'Intro.\n\n#### Codex voice mode\n\nBody.'} />);
    const h4 = within(container).getByRole('heading', { level: 4, name: 'Codex voice mode' });
    expect(h4.className).toContain('font-semibold');
    expect(h4.className).toContain('text-pretty');
    expect(h4).toHaveAttribute('dir', 'auto');
    expect(h4.className).not.toBe(container.querySelector('p')!.className);
  });

  it('gives every heading level a semibold, pretty-wrapped style on one scale (h6 muted, never coloured)', () => {
    const { container } = rtlRender(
      <MarkdownRenderer content={'# One\n\n## Two\n\n### Three\n\n#### Four\n\n##### Five\n\n###### Six\n\nBody.'} />,
    );
    const scale = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6')).map((h) => ({
      tag: h.tagName.toLowerCase(),
      dir: h.getAttribute('dir'),
      semibold: h.className.includes('font-semibold'),
      pretty: h.className.includes('text-pretty'),
      size: /text-\[([\d.]+em)\]/.exec(h.className)?.[1],
      tone: /\btext-(fg(?:-\d)?)\b/.exec(h.className)?.[1],
    }));
    expect(scale).toEqual([
      { tag: 'h1', dir: 'auto', semibold: true, pretty: true, size: '1.5em', tone: 'fg' },
      { tag: 'h2', dir: 'auto', semibold: true, pretty: true, size: '1.25em', tone: 'fg' },
      { tag: 'h3', dir: 'auto', semibold: true, pretty: true, size: '1.05em', tone: 'fg' },
      { tag: 'h4', dir: 'auto', semibold: true, pretty: true, size: '1em', tone: 'fg' },
      { tag: 'h5', dir: 'auto', semibold: true, pretty: true, size: '0.95em', tone: 'fg' },
      { tag: 'h6', dir: 'auto', semibold: true, pretty: true, size: '0.95em', tone: 'fg-2' },
    ]);
  });

  it('dedents indented HTML so markdown does not read it as code', () => {
    expect(normalizeRendererContent('\n    <p>Hello</p>\n    <p>World</p>')).toBe('\n<p>Hello</p>\n<p>World</p>');
    // Plain markdown with an indented code block is left alone.
    expect(normalizeRendererContent('Text\n\n    code')).toBe('Text\n\n    code');
  });
});

// ---- Mark IX F3: the post page reads through usePost and follows the feed context ----

const NEXT_ID = '9c1d5c1e-2f4b-4f3a-9a49-6f2b1d7e0a11';
const PREV_ID = '1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d';
const CTX = 'all:unread:';

function detailFor(post: Post) {
  return { success: true, post, reader_state: null };
}

function contextApi(methods: Partial<Record<keyof Api, unknown>> = {}) {
  const posts: Record<string, Post> = {
    [PREV_ID]: rssPost({ id: PREV_ID, title: 'The newer post', source: 'newer-source', published_at: '2026-09-28T10:00:00+00:00' }),
    [POST_ID]: rssPost(),
    [NEXT_ID]: rssPost({ id: NEXT_ID, title: 'The older post', source: 'older-source', published_at: '2026-09-26T10:00:00+00:00' }),
  };
  return makeFakeApi({
    getPostDetail: vi.fn((id: string) => Promise.resolve(detailFor(posts[id]))),
    getFeed: vi.fn().mockResolvedValue(feedPage([
      feedItem({ id: PREV_ID, title: 'The newer post', sort_at: '2026-09-28T10:00:00+00:00' }),
      feedItem({ id: POST_ID, title: '2026 in LLMs (so far)', sort_at: '2026-09-27T23:54:15+00:00' }),
      feedItem({ id: NEXT_ID, title: 'The older post', sort_at: '2026-09-26T10:00:00+00:00' }),
    ])),
    recordPostOpen: vi.fn().mockResolvedValue({ success: true }),
    recordPostReadingSession: vi.fn().mockResolvedValue({ success: true }),
    setPostsRead: vi.fn().mockResolvedValue({ success: true }),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 0, by_source: {}, by_folder: {} }),
    ...methods,
  });
}

function FeedProbe() {
  const location = useLocation();
  return <p data-testid="feed">{location.pathname + location.search}</p>;
}

function renderAt(api: Api, route: string, queryClient?: ReturnType<typeof makeTestQueryClient>) {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<FeedProbe />} />
      <Route path="/posts/:postId" element={<PostDetailPage />} />
    </Routes>,
    { api, route, queryClient },
  );
}

describe('PostDetailPage loading', () => {
  it('opens a post the feed prefetched straight from the cache: no skeleton, no second request', () => {
    const api = contextApi();
    const queryClient = makeTestQueryClient();
    queryClient.setQueryData(postKey(POST_ID), detailFor(rssPost()));
    renderAt(api, `/posts/${POST_ID}`, queryClient);
    expect(screen.getByRole('heading', { level: 1, name: '2026 in LLMs (so far)' })).toBeInTheDocument();
    expect(screen.queryByText('Loading post')).toBeNull();
    expect(api.getPostDetail).not.toHaveBeenCalled();
  });
});

describe('PostDetailPage feed context and keys', () => {
  it('j and k follow the feed order from ?ctx=; each open is recorded with that post’s own metadata', async () => {
    const user = userEvent.setup();
    const api = contextApi();
    renderAt(api, `/posts/${POST_ID}?ctx=${encodeURIComponent(CTX)}`);
    await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    const top = screen.getByRole('navigation', { name: 'Post navigation' });
    await waitFor(() => expect(within(top).getByRole('button', { name: 'Next' })).toBeEnabled());

    await user.keyboard('j');
    expect(await screen.findByRole('heading', { level: 1, name: 'The older post' })).toBeInTheDocument();
    await user.keyboard('k');
    expect(await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' })).toBeInTheDocument();

    await waitFor(() => expect(api.recordPostOpen).toHaveBeenCalledTimes(3));
    const opens = vi.mocked(api.recordPostOpen).mock.calls;
    expect(opens[1]).toEqual([NEXT_ID, expect.objectContaining({ title: 'The older post', source: 'older-source' })]);
    expect(opens[0]).toEqual([POST_ID, expect.objectContaining({ title: '2026 in LLMs (so far)' })]);
    // Moving on within a second is not a reading session (no fake 1-second sessions).
    expect(api.recordPostReadingSession).not.toHaveBeenCalled();
  });

  it('u goes back to the feed of the context; m toggles read; ? opens the shortcut help', async () => {
    const user = userEvent.setup();
    const api = contextApi();
    renderAt(api, `/posts/${POST_ID}?ctx=${encodeURIComponent('all:starred:')}`);
    await screen.findByRole('heading', { level: 1 });

    // Opening marks the post read (server side, mirrored here), so m marks it unread.
    await waitFor(() => expect(api.recordPostOpen).toHaveBeenCalled());
    await user.keyboard('m');
    await waitFor(() => expect(api.setPostsRead).toHaveBeenCalledWith([POST_ID], false));
    await user.keyboard('m');
    await waitFor(() => expect(api.setPostsRead).toHaveBeenLastCalledWith([POST_ID], true));

    await user.keyboard('?');
    const dialog = await screen.findByRole('dialog', { name: /keyboard shortcuts/i });
    expect(within(dialog).getByText('Next / previous post in the feed')).toBeInTheDocument();
    expect(within(dialog).queryByText(/fetch/i)).toBeNull();     // fetching lives in Sources
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

    await user.keyboard('u');
    expect(await screen.findByTestId('feed')).toHaveTextContent('/?filter=starred');
  });

  it('without a context j does nothing and the way out is a visible "Back to feed"', async () => {
    const user = userEvent.setup();
    const api = contextApi();
    renderAt(api, `/posts/${POST_ID}`);
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull();
    await user.keyboard('j');
    expect(api.getFeed).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { level: 1, name: '2026 in LLMs (so far)' })).toBeInTheDocument();
    await user.click(within(screen.getByRole('navigation', { name: 'Post navigation' })).getByRole('button', { name: 'Back to feed' }));
    expect(await screen.findByTestId('feed')).toHaveTextContent('/');
  });

  it('without a context the shortcut help lists no j / k for the post (issue 0027)', async () => {
    const user = userEvent.setup();
    renderAt(contextApi(), `/posts/${POST_ID}`);
    await screen.findByRole('heading', { level: 1 });
    await user.keyboard('?');
    const dialog = await screen.findByRole('dialog', { name: /keyboard shortcuts/i });
    expect(within(dialog).queryByText('Next / previous post in the feed')).toBeNull();
    expect(within(dialog).getByText('Next / previous item (loads more at the end)')).toBeInTheDocument();
  });

  it('repeats Back / Previous / Next after the post, and they move like the top row (issue 0010)', async () => {
    const user = userEvent.setup();
    const api = contextApi();
    renderAt(api, `/posts/${POST_ID}?ctx=${encodeURIComponent(CTX)}`);
    await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    const end = screen.getByRole('navigation', { name: 'After the post' });
    await waitFor(() => expect(within(end).getByRole('button', { name: 'Next' })).toBeEnabled());

    await user.click(within(end).getByRole('button', { name: 'Next' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'The older post' })).toBeInTheDocument();
    const endAgain = screen.getByRole('navigation', { name: 'After the post' });
    await waitFor(() => expect(within(endAgain).getByRole('button', { name: 'Previous' })).toBeEnabled());
    await user.click(within(endAgain).getByRole('button', { name: 'Previous' }));
    expect(await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' })).toBeInTheDocument();
  });

  it('Esc leaves the post like u', async () => {
    const user = userEvent.setup();
    renderAt(contextApi(), `/posts/${POST_ID}?ctx=${encodeURIComponent(CTX)}`);
    await screen.findByRole('heading', { level: 1 });
    await user.keyboard('{Escape}');
    expect(await screen.findByTestId('feed')).toHaveTextContent('/');
  });
});

// ---- issue 0014: continuous reading, with a stubbed IntersectionObserver ----

/** Observers are fired by hand: `see(element)` says the element entered its observer's root. */
class StubObserver {
  static all: StubObserver[] = [];
  readonly targets = new Set<Element>();
  constructor(readonly callback: IntersectionObserverCallback) { StubObserver.all.push(this); }
  observe(target: Element) { this.targets.add(target); }
  unobserve(target: Element) { this.targets.delete(target); }
  disconnect() { this.targets.clear(); }
  takeRecords() { return []; }
}

function see(target: Element | null) {
  if (!target) throw new Error('nothing to see');
  act(() => {
    for (const observer of [...StubObserver.all]) {
      if (!observer.targets.has(target)) continue;
      observer.callback([{ target, isIntersecting: true } as unknown as IntersectionObserverEntry], observer as unknown as IntersectionObserver);
    }
  });
}

const postEnd = (id: string) => document.querySelector(`[data-post-end="${id}"]`);
const slot = (id: string) => document.querySelector(`[data-post-slot="${id}"]`);
const streamEnd = () => document.querySelector('[data-stream-end]');

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="at">{location.pathname}</p>;
}

/** The feed, then the post opened from it: Back from the post returns to the feed. */
function renderStream(api: Api, postId = POST_ID, ctx = CTX) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/" element={<FeedProbe />} />
        <Route path="/posts/:postId" element={<PostDetailPage />} />
      </Routes>
      <LocationProbe />
    </>,
    { api, route: ['/', `/posts/${postId}?ctx=${encodeURIComponent(ctx)}`] },
  );
}

async function nextReady() {
  const top = screen.getByRole('navigation', { name: 'Post navigation' });
  await waitFor(() => expect(within(top).getByRole('button', { name: 'Next' })).toBeEnabled());
}

describe('PostDetailPage continuous reading (issue 0014)', () => {
  beforeEach(() => {
    StubObserver.all = [];
    vi.stubGlobal('IntersectionObserver', StubObserver);
    window.localStorage.clear();
    resetStoredChoices();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('the next post of the feed follows below once the end of the stream is seen', async () => {
    renderStream(contextApi());
    await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    await nextReady();
    expect(screen.queryByRole('heading', { level: 1, name: 'The older post' })).toBeNull();

    see(streamEnd());
    expect(await screen.findByRole('heading', { level: 1, name: 'The older post' })).toBeInTheDocument();
    expect(screen.getAllByRole('article', { name: 'Post content' })).toHaveLength(2);
    expect(screen.queryByText('You’re all caught up')).toBeNull();
  });

  it('the address follows the post in view by replacing it, so Back still leaves for the list', async () => {
    const user = userEvent.setup();
    renderStream(contextApi());
    await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    await nextReady();
    see(streamEnd());
    await screen.findByRole('heading', { level: 1, name: 'The older post' });

    see(slot(NEXT_ID));
    expect(screen.getByTestId('at')).toHaveTextContent(`/posts/${NEXT_ID}`);
    expect(screen.getAllByRole('article', { name: 'Post content' })).toHaveLength(2);

    await user.keyboard('u');
    expect(await screen.findByTestId('feed')).toHaveTextContent('/');
  });

  it('marks a post read only once its end has passed, not when it appears', async () => {
    const api = contextApi();
    renderStream(api);
    await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    await nextReady();
    expect(api.recordPostOpen).not.toHaveBeenCalled();

    see(postEnd(POST_ID));
    await waitFor(() => expect(api.recordPostOpen).toHaveBeenCalledTimes(1));
    expect(api.recordPostOpen).toHaveBeenCalledWith(POST_ID, expect.anything());

    see(streamEnd());
    await screen.findByRole('heading', { level: 1, name: 'The older post' });
    expect(api.recordPostOpen).toHaveBeenCalledTimes(1);
    see(postEnd(NEXT_ID));
    await waitFor(() => expect(api.recordPostOpen).toHaveBeenLastCalledWith(NEXT_ID, expect.anything()));
  });

  it('the next post starts after a plain rule: its header already names its source and title (issue 0027)', async () => {
    renderStream(contextApi());
    await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    await nextReady();
    see(streamEnd());
    await screen.findByRole('heading', { level: 1, name: 'The older post' });
    expect(screen.getAllByText('The older post')).toHaveLength(1);
  });

  it('j and k move between the posts in the stream', async () => {
    const user = userEvent.setup();
    renderStream(contextApi());
    await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    await nextReady();
    see(streamEnd());
    await screen.findByRole('heading', { level: 1, name: 'The older post' });

    await user.keyboard('j');
    expect(screen.getByTestId('at')).toHaveTextContent(`/posts/${NEXT_ID}`);
    await user.keyboard('k');
    expect(screen.getByTestId('at')).toHaveTextContent(`/posts/${POST_ID}`);
    expect(screen.getAllByRole('article', { name: 'Post content' })).toHaveLength(2);
  });

  it('ends with "You’re all caught up" and Back / Previous / Next after the last post', async () => {
    renderStream(contextApi(), NEXT_ID);
    await screen.findByRole('heading', { level: 1, name: 'The older post' });
    expect(await screen.findByText('You’re all caught up')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'After the post' })).toBeInTheDocument();
  });

  it.each(['all:starred:', 'all:all:'])('under %s the stream ends with "You’ve reached the end", as the list does (issue 0027)', async (ctx) => {
    renderStream(contextApi(), NEXT_ID, ctx);
    await screen.findByRole('heading', { level: 1, name: 'The older post' });
    expect(await screen.findByText('You’ve reached the end')).toBeInTheDocument();
    expect(screen.queryByText('You’re all caught up')).toBeNull();
  });

  it('one post at a time renders a single article and records the open at once', async () => {
    window.localStorage.setItem('insight.reader.flow', 'single');
    const api = contextApi();
    renderStream(api);
    await screen.findByRole('heading', { level: 1, name: '2026 in LLMs (so far)' });
    await nextReady();
    expect(streamEnd()).toBeNull();
    expect(screen.getAllByRole('article', { name: 'Post content' })).toHaveLength(1);
    expect(screen.getByRole('navigation', { name: 'After the post' })).toBeInTheDocument();
    await waitFor(() => expect(api.recordPostOpen).toHaveBeenCalledWith(POST_ID, expect.anything()));
  });
});

// ---- issue 0030: continue where I stopped ----

/** A long post: 40 paragraphs, about 5,000 characters (more than three screens). */
const PARAGRAPHS = Array.from({ length: 40 }, (_, i) => `Paragraph ${i + 1}. ${'Agents shipped everywhere this year and the tools got better. '.repeat(2)}`);
function longPost(overrides: Partial<Post> = {}) {
  return rssPost({
    content: PARAGRAPHS.join('\n\n'),
    content_html: PARAGRAPHS.map((text) => `<p>${text}</p>`).join(''),
    ...overrides,
  });
}

function positionApi(post: Post, resume: { resume_block?: number | null; resume_blocks?: number | null } = {}) {
  return baseApi(post, {
    getPostDetail: vi.fn().mockResolvedValue({
      success: true, post, reader_state: { post_id: post.id, is_favorited: false, open_count: 1, ...resume },
    }),
    savePostPosition: vi.fn().mockResolvedValue({ success: true }),
  });
}

const OFFER = /continue from where you stopped/i;

/** Lay the body out as if scrolled so that paragraph `top` (0-based) is the first in view. */
function scrollTo(top: number) {
  const article = screen.getByRole('article', { name: 'Post content' });
  article.getBoundingClientRect = () => ({ top: -top * 100 - 50, bottom: (40 - top) * 100 } as DOMRect);
  article.querySelectorAll('p').forEach((node, i) => {
    node.getBoundingClientRect = () => ({ top: (i - top) * 100, bottom: (i - top) * 100 + 90 } as DOMRect);
  });
  fireEvent.scroll(window);
}

describe('PostDetailPage continue where I stopped (issue 0030)', () => {
  beforeEach(() => {
    StubObserver.all = [];
    vi.stubGlobal('IntersectionObserver', StubObserver);
    window.localStorage.clear();
    resetStoredChoices();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
  });

  it('offers to continue a long post left part way, and only scrolls when asked', async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    render(positionApi(longPost(), { resume_block: 16, resume_blocks: 40 }));
    const offer = await screen.findByRole('button', { name: 'Continue from where you stopped (40%)' });
    expect(scrollIntoView).not.toHaveBeenCalled();

    await user.click(offer);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    const target = scrollIntoView.mock.contexts[0] as HTMLElement;
    expect(target.textContent).toMatch(/^Paragraph 17\./);
    expect(document.activeElement).toBe(target);
    expect(screen.queryByRole('button', { name: OFFER })).toBeNull();
  });

  it.each([
    ['barely started (under 5%)', longPost(), { resume_block: 1, resume_blocks: 40 }],
    ['nearly finished (over 90%)', longPost(), { resume_block: 38, resume_blocks: 40 }],
    ['never started', longPost(), {}],
    ['a short post', rssPost(), { resume_block: 1, resume_blocks: 2 }],
  ])('offers nothing for %s', async (_, post, resume) => {
    render(positionApi(post, resume));
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByRole('button', { name: OFFER })).toBeNull();
  });

  it('saves the top block in view a few seconds after scrolling stops, not on every scroll', async () => {
    const api = positionApi(longPost());
    render(api);
    await screen.findByRole('heading', { level: 1 });
    vi.useFakeTimers();
    scrollTo(8);
    act(() => { vi.advanceTimersByTime(2000); });
    scrollTo(10);
    act(() => { vi.advanceTimersByTime(2000); });
    expect(api.savePostPosition).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1500); });
    expect(api.savePostPosition).toHaveBeenCalledTimes(1);
    expect(api.savePostPosition).toHaveBeenCalledWith(POST_ID, 10, 40);
  });

  it('saves at once on leaving: the tab hidden, or the post closed', async () => {
    const api = positionApi(longPost());
    const { unmount } = render(api);
    await screen.findByRole('heading', { level: 1 });
    scrollTo(12);
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    expect(api.savePostPosition).toHaveBeenLastCalledWith(POST_ID, 12, 40);

    scrollTo(20);
    unmount();
    expect(api.savePostPosition).toHaveBeenLastCalledWith(POST_ID, 20, 40);
  });

  it('nothing is saved before you scroll: opening a post keeps where you stopped', async () => {
    const api = positionApi(longPost(), { resume_block: 16, resume_blocks: 40 });
    const { unmount } = render(api);
    await screen.findByRole('button', { name: OFFER });
    unmount();
    expect(api.savePostPosition).not.toHaveBeenCalled();
  });

  it('while the offer stands, looking about above the old place keeps it; reading past it replaces it', async () => {
    const api = positionApi(longPost(), { resume_block: 16, resume_blocks: 40 });
    const { unmount } = render(api);
    await screen.findByRole('button', { name: OFFER });
    scrollTo(3);
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    expect(api.savePostPosition).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: OFFER })).toBeInTheDocument();

    scrollTo(18);
    unmount();
    expect(api.savePostPosition).toHaveBeenCalledWith(POST_ID, 18, 40);
  });

  it('reaching the end clears the position, and reading back up does not store it again', async () => {
    const api = positionApi(longPost(), { resume_block: 16, resume_blocks: 40 });
    const { unmount } = render(api);
    await screen.findByRole('button', { name: OFFER });
    see(postEnd(POST_ID));
    await waitFor(() => expect(api.savePostPosition).toHaveBeenCalledWith(POST_ID, null, null));
    scrollTo(5);
    unmount();
    expect(api.savePostPosition).toHaveBeenCalledTimes(1);
  });

  it('in the stream only the post opened offers to continue, not one that joins below', async () => {
    const posts: Record<string, Post> = { [POST_ID]: longPost(), [NEXT_ID]: longPost({ id: NEXT_ID, title: 'The older post' }) };
    const api = contextApi({
      getPostDetail: vi.fn((id: string) => Promise.resolve({
        success: true, post: posts[id], reader_state: { post_id: id, resume_block: 16, resume_blocks: 40 },
      })),
      savePostPosition: vi.fn().mockResolvedValue({ success: true }),
    });
    renderStream(api);
    expect(await screen.findByRole('button', { name: OFFER })).toBeInTheDocument();
    await nextReady();
    see(streamEnd());
    await screen.findByRole('heading', { level: 1, name: 'The older post' });
    expect(screen.getAllByRole('button', { name: OFFER })).toHaveLength(1);
  });
});
