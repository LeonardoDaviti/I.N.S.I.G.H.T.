import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { Toaster } from 'sonner';

import DailyBriefing from './DailyBriefing';
import { apiService } from '../services/api';
import type { Post } from '../services/api';
import { localDateISO } from '../lib/dates';

// The briefings restyle (Mark IX): newsletter layout, monochrome, generation unchanged.

const CHROMATIC = /\b(?:bg|text|border|ring)-(?:red|blue|indigo|amber|emerald|teal|green|purple|rose|sky|orange|cyan)-\d/;
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

const post = (id: string, extra: Partial<Post> = {}): Post =>
  ({ id, title: `Post ${id}`, platform: 'reddit', source: 'r/LocalLLaMA', url: `https://example.com/${id}`, date: '2026-09-29T10:00:00Z', content: 'Body', media_urls: [], ...extra }) as Post;

function stubCommon(status: Record<string, unknown> = { success: true, corpus: {} }) {
  vi.spyOn(apiService, 'getSourcesWithCounts').mockResolvedValue({ success: true, total_posts: 12, platforms: {} } as never);
  vi.spyOn(apiService, 'getStatus').mockResolvedValue(status as never);
}

function renderAt(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <DailyBriefing />
      <Toaster />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('DailyBriefing (Mark IX)', () => {
  it('reads a daily briefing deep link as a dated issue, without colour or emoji', async () => {
    stubCommon();
    const generate = vi.spyOn(apiService, 'generateBriefing').mockResolvedValue({
      success: true,
      briefing: '## Main developments\n\n- One thing happened.',
      date: '2026-09-29',
      posts_processed: 12847,
      one_sentence_takeaway: 'Frontier labs cut prices.',
      references: [{ id: 'r1', post_id: 'p1', post: post('p1', { title: 'A cited post' }) }],
    });

    const { container } = renderAt('/briefing?mode=daily&date=2026-09-29');

    expect(await screen.findByRole('heading', { level: 2, name: 'Daily briefing' })).toBeInTheDocument();
    expect(generate).toHaveBeenCalledWith('2026-09-29');
    expect(screen.getAllByText('Tuesday, 29 September 2026').length).toBeGreaterThan(0);
    expect(screen.getByText('Frontier labs cut prices.')).toBeInTheDocument();
    // Counts go through Intl: 12,847 posts, not 12847.
    expect(screen.getAllByText(/12,847 posts/).length).toBeGreaterThan(0);
    const refs = screen.getByRole('region', { name: 'Referenced posts' });
    expect(within(refs).getByRole('button', { name: 'A cited post' })).toBeInTheDocument();

    expect(container.innerHTML).not.toMatch(CHROMATIC);
    expect(container.textContent).not.toMatch(EMOJI);
    expect(screen.queryByText('I.N.S.I.G.H.T.')).not.toBeInTheDocument();
  });

  it('without a newest post it opens on the local day and offers all posts when it is empty', async () => {
    stubCommon();
    const daily = vi.spyOn(apiService, 'getDailyPosts').mockResolvedValue({ success: true, posts: [], total: 0, date: '', source: 'database' });

    renderAt('/briefing');

    await waitFor(() => expect(daily).toHaveBeenCalledWith(localDateISO()));
    expect(await screen.findByText(/^No posts on /)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show all posts' })).toBeInTheDocument();
  });

  it('shows failing sources as an inverted "×" status that links to the health table', async () => {
    stubCommon({ success: true, corpus: { posts_last_24h: 1284 }, source_health_summary: { errors: 3 }, gemini_configured: false });
    vi.spyOn(apiService, 'getDailyPosts').mockResolvedValue({ success: true, posts: [], total: 0, date: '', source: 'database' });

    renderAt('/briefing');

    const link = await screen.findByRole('link', { name: /3 source errors/ });
    expect(link).toHaveAttribute('href', '/settings/sources?tab=health&status=error');
    expect(link.querySelector('[data-status="failing"]')).not.toBeNull();
    expect(screen.getByText('1,284 posts / 24h')).toBeInTheDocument();
    expect(screen.getByText('Gemini key missing').closest('[data-status]')).toHaveAttribute('data-status', 'unavailable');
  });

  it('opens on the latest day that has posts, not on an empty today', async () => {
    stubCommon({ success: true, corpus: { latest_post_at: '2026-09-29T10:00:00Z', latest_fetch_at: new Date().toISOString() } });
    const daily = vi
      .spyOn(apiService, 'getDailyPosts')
      .mockResolvedValue({ success: true, posts: [post('p1')], total: 1, date: '2026-09-29', source: 'database' });

    renderAt('/briefing');

    await waitFor(() => expect(daily).toHaveBeenCalledWith(localDateISO(new Date('2026-09-29T10:00:00Z'))));
    expect(daily).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole('heading', { name: /Posts of the day/ })).toBeInTheDocument();
    expect(screen.queryByTestId('stale-warning')).not.toBeInTheDocument();
  });

  it('makes a stopped ingestion one loud warning line', async () => {
    stubCommon({ success: true, corpus: { latest_post_at: '2026-09-29T10:00:00Z', latest_fetch_at: '2026-09-30T08:00:00Z' } });
    vi.spyOn(apiService, 'getDailyPosts').mockResolvedValue({ success: true, posts: [], total: 0, date: '', source: 'database' });

    renderAt('/briefing');

    const warning = await screen.findByTestId('stale-warning');
    expect(warning).toHaveAttribute('data-state', 'stopped');
    expect(warning).toHaveTextContent(/stopped/);
    expect(warning).toHaveTextContent(/Nothing fetched for \d+d\./);
    expect(within(warning).getByRole('link', { name: 'Open ingestion' })).toHaveAttribute('href', '/ingestion');
  });

  it('has one tab per briefing kind and one primary action per tab', async () => {
    stubCommon();
    vi.spyOn(apiService, 'getDailyPosts').mockResolvedValue({ success: true, posts: [], total: 0, date: '', source: 'database' });
    const generate = vi.spyOn(apiService, 'generateBriefingWithTopics');
    const user = userEvent.setup();

    renderAt('/briefing');

    const tabs = await screen.findByRole('tablist', { name: 'Briefing kinds' });
    expect(within(tabs).getAllByRole('tab').map((t) => t.textContent)).toEqual(['daily', 'topics', 'weekly']);
    expect(screen.getByRole('link', { name: 'vertical' })).toHaveAttribute('href', '/briefing/vertical');
    // Everything the top bar files under "briefings" is in the section's own row.
    expect(screen.getByRole('link', { name: 'stories' })).toHaveAttribute('href', '/stories');
    expect(screen.getByRole('link', { name: 'inbox' })).toHaveAttribute('href', '/inbox');
    await screen.findByRole('heading', { name: /Posts of the day/ });
    expect(screen.getByRole('button', { name: 'Generate briefing' })).toBeInTheDocument();

    await user.click(within(tabs).getByRole('tab', { name: 'topics' }));
    expect(screen.getByRole('button', { name: 'Generate topic briefing' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Generate briefing' })).not.toBeInTheDocument();
    expect(screen.getByText(/^No topics for /)).toBeInTheDocument();
    // Switching tabs never generates anything (no model call on navigation).
    expect(generate).not.toHaveBeenCalled();

    await user.click(within(tabs).getByRole('tab', { name: 'weekly' }));
    expect(screen.getByRole('button', { name: 'Generate weekly briefing' })).toBeInTheDocument();
    // No verb rail any more: navigation lives in the top bar.
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  });

  it('reports a moved post as a success toast, not in the error slot', async () => {
    stubCommon();
    vi.spyOn(apiService, 'getTopicsByDate').mockResolvedValue({
      success: true,
      date: '2026-09-29',
      total: 1,
      topics: [{ id: 't1', title: 'Agents', summary: null, posts: [post('p1'), post('p2')] }],
    });
    const move = vi.spyOn(apiService, 'movePostToOutlier').mockResolvedValue({ success: true, message: 'Moved to outliers', outlier_topic_id: 'o1' } as never);
    const user = userEvent.setup();

    renderAt('/briefing?mode=db-topics&date=2026-09-29&topic=t1');

    const entries = await screen.findAllByTestId('post-entry');
    expect(entries).toHaveLength(2);
    await user.click(within(entries[0]).getByRole('button', { name: 'move to outlier' }));

    expect(move).toHaveBeenCalledWith('t1', 'p1', '2026-09-29');
    expect(await screen.findByText('Moved to outliers')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('post-entry')).toHaveLength(1);
  });

  it('keeps post titles and the preview toggle accessible', async () => {
    stubCommon();
    vi.spyOn(apiService, 'getDailyPosts').mockResolvedValue({
      success: true,
      posts: [post('p1', { title: '', content: 'Hidden body' })],
      total: 1,
      date: '2026-09-29',
      source: 'database',
    });
    const user = userEvent.setup();

    renderAt('/briefing?mode=db-posts&date=2026-09-29');

    // A missing title falls back to the platform, never an empty heading; it links to the post.
    const title = await screen.findByRole('link', { name: 'Reddit post' });
    expect(title).toHaveAttribute('href', '/posts/p1');
    const entry = screen.getByTestId('post-entry');
    // The source name is the only meta: no platform word.
    expect(entry).not.toHaveTextContent(/\breddit\b/);
    const preview = within(entry).getByRole('button', { name: 'preview' });
    expect(preview).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Hidden body')).not.toBeInTheDocument();
    await user.click(preview);
    expect(within(entry).getByRole('button', { name: 'hide' })).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByText('Hidden body')).toBeInTheDocument();
  });
});
