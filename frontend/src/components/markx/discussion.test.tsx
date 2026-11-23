// The post page's Discussion (0280), its header link, and News rows' "discussion: N points". Synthetic data only.
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXDiscussion from './MarkXDiscussion';
import type { MarkxDiscussion } from '../../services/markx';
import type { FeedItem } from '../../services/api';
import { DiscussionLink } from '../../pages/PostDetailPage';
import { discussionWords } from '../../lib/discussion';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const THREAD = { host: 'hn', name: 'Hacker News', url: 'https://news.ycombinator.com/item?id=1', total: 279, kept: 200,
  fetched_at: '2026-11-23T10:00:00+00:00', next_at: null, failed: null };
const ANSWERED: MarkxDiscussion = {
  thread: THREAD, status: 'answered', wanted: true, dropped: 0,
  stance: 'Mostly agrees; adds that macOS already compresses memory.',
  points: [{ kind: 'context', text: 'macOS compresses memory by default.', quote: 'macOS does this by default',
    comments: ['c11'] }],
  tools: [{ name: 'zswap', url: 'https://example.org/zswap', what: null, comments: ['c11'] }],
  comments: { c11: { id: '11', parent: null, author: 'user0', score: null, at: null,
    text: 'As others have said, macOS does this by default.', url: 'https://news.ycombinator.com/item?id=11' } },
};

describe('Discussion (0280)', () => {
  it('shows the stance, each point with its quote, its cited comments on expand, and the tools', async () => {
    const getMarkxDiscussion = vi.fn().mockResolvedValue(ANSWERED);
    const wantMarkxDiscussion = vi.fn();
    renderWithProviders(<MarkXDiscussion postId="p1" />, { api: makeFakeApi({ getMarkxDiscussion, wantMarkxDiscussion }) });
    expect(await screen.findByText('1 point · 279 comments on Hacker News')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Discussion'));
    expect(screen.getByText(ANSWERED.stance!)).toBeInTheDocument();
    expect(screen.getByText('“macOS does this by default”')).toBeInTheDocument();
    await userEvent.click(screen.getByText('1 comment'));
    expect(screen.getByText('user0')).toBeVisible();
    expect(screen.getByRole('link', { name: 'open' }).getAttribute('href')).toBe('https://news.ycombinator.com/item?id=11');
    expect(screen.getByRole('link', { name: 'zswap' }).getAttribute('href')).toBe('https://example.org/zswap');
    expect(screen.getByRole('link', { name: 'the thread on Hacker News' }).getAttribute('href')).toBe(THREAD.url);
    expect(wantMarkxDiscussion).not.toHaveBeenCalled();   // already wanted
  });

  it('wants a thread nobody asked for once, then reads the view again', async () => {
    const waiting: MarkxDiscussion = { ...ANSWERED, status: 'waiting', wanted: false, stance: null, points: [], tools: [],
      comments: {}, thread: { ...THREAD, total: null, kept: null, fetched_at: null } };
    const getMarkxDiscussion = vi.fn().mockResolvedValueOnce(waiting).mockResolvedValue({ ...waiting, wanted: true });
    const wantMarkxDiscussion = vi.fn().mockResolvedValue({ wanted: true });
    renderWithProviders(<MarkXDiscussion postId="p1" />, { api: makeFakeApi({ getMarkxDiscussion, wantMarkxDiscussion }) });
    expect(await screen.findByText('Reading the thread…')).toBeInTheDocument();
    await waitFor(() => expect(getMarkxDiscussion).toHaveBeenCalledTimes(2));
    expect(wantMarkxDiscussion).toHaveBeenCalledTimes(1);
    expect(wantMarkxDiscussion).toHaveBeenCalledWith('p1');
  });

  it('says when the thread adds nothing, and shows nothing for a post without one', async () => {
    const none = { ...ANSWERED, points: [], tools: [], comments: {} };
    const { unmount } = renderWithProviders(<MarkXDiscussion postId="p1" />, {
      api: makeFakeApi({ getMarkxDiscussion: vi.fn().mockResolvedValue(none) }) });
    await userEvent.click(await screen.findByText('Discussion'));
    expect(screen.getByText('Nothing the post doesn’t say.')).toBeInTheDocument();
    unmount();
    const { container } = renderWithProviders(<MarkXDiscussion postId="p2" />, {
      api: makeFakeApi({ getMarkxDiscussion: vi.fn().mockResolvedValue({ ...none, thread: null, status: 'none' }) }) });
    await waitFor(() => expect(container.querySelector('[data-discussion]')).toBeNull());
  });

  it('links the thread in the header, with its count once fetched', () => {
    const { rerender } = render(<DiscussionLink discussion={{ name: 'Hacker News', url: THREAD.url, total: null }} />);
    const link = screen.getByRole('link', { name: 'Discussion on Hacker News' });
    expect(link.getAttribute('href')).toBe(THREAD.url);
    expect(link.getAttribute('target')).toBe('_blank');
    rerender(<DiscussionLink discussion={{ name: 'Hacker News', url: THREAD.url, total: 279 }} />);
    expect(screen.getByRole('link', { name: 'Discussion on Hacker News · 279 comments' })).toBeInTheDocument();
  });

  it('a News row says how many points its posts\' threads add', () => {
    const item = { id: 'lead', story: { posts: [{ id: 'hn1' }, { id: 'lead' }] } } as unknown as FeedItem;
    expect(discussionWords(item, { hn1: { points: 3, total: 279, name: 'Hacker News' } })).toBe('discussion: 3 points');
    expect(discussionWords(item, {})).toBeNull();
    expect(discussionWords(item, undefined)).toBeNull();
  });
});
