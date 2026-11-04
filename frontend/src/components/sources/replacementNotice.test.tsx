import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import ReplacementNotice from './ReplacementNotice';
import { healthRow } from '../ops/fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { SourceHealthRow, SourceReplacement } from '../../services/api';

const now = new Date('2026-10-28T09:00:00Z');
const feed: SourceReplacement = { kind: 'feed', url: 'https://arena.ai/blog/feed.xml', title: 'Arena blog', found: null, prefix: null };
const page: SourceReplacement = { kind: 'page_watch', url: 'https://arena.ai/blog/', title: 'arena.ai/blog', found: 76, prefix: '/blog/' };

function broken(over: Partial<SourceHealthRow> = {}) {
  return healthRow({ source_id: 's1', status: 'backoff', consecutive_failures: 3, doctor_looked_at: '2026-10-28T07:00:00Z', ...over }, now);
}

function setup(row: SourceHealthRow, api: Record<string, unknown> = {}) {
  const onSwitched = vi.fn();
  renderWithProviders(<ReplacementNotice row={row} now={now} onSwitched={onSwitched} />, { api: makeFakeApi(api) });
  return { onSwitched };
}

describe('ReplacementNotice', () => {
  it('says a server error is the server failing, retried, not a source that stopped (issue 0072 D3)', () => {
    setup(broken({ doctor_looked_at: null, replacement: null, server_error: { status: 502, site: 'example.org' } }));
    expect(screen.getByText("example.org is failing (HTTP 502): its own server didn't answer, usually temporary.")).toBeInTheDocument();
    expect(screen.getByText("The address hasn't moved; INSIGHT keeps retrying.")).toBeInTheDocument();
    expect(screen.queryByText('This source stopped working.')).not.toBeInTheDocument();
  });

  it('names the site on a timeout too (issue 0086)', () => {
    setup(broken({ doctor_looked_at: null, replacement: null, server_error: { status: null, site: 'example.org' } }));
    expect(screen.getByText("example.org is failing (no answer in time): its own server didn't answer, usually temporary.")).toBeInTheDocument();
  });

  it('offers the feed it found, by title and address', () => {
    setup(broken({ replacement: feed }));
    expect(screen.getByText('This source stopped working.')).toBeInTheDocument();
    expect(screen.getByText('INSIGHT found a replacement: Arena blog (https://arena.ai/blog/feed.xml)')).toBeInTheDocument();
  });

  it("previews the replacement's latest titles before Switch", () => {
    setup(broken({ replacement: { ...feed, shared: 2, latest: ['A first post', 'A second post'] } }));
    expect(screen.getByText('Its latest posts')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['A first post', 'A second post']);
    expect(screen.getByRole('button', { name: 'Switch' })).toBeInTheDocument();
  });

  it('offers a page to follow with its article count', () => {
    setup(broken({ replacement: page }));
    expect(screen.getByText('INSIGHT found a replacement: Follow arena.ai/blog: 76 articles')).toBeInTheDocument();
  });

  it('Switch points the source at the feed', async () => {
    const switchSource = vi.fn().mockResolvedValue({ success: true });
    const { onSwitched } = setup(broken({ replacement: feed }), { switchSource });
    fireEvent.click(screen.getByRole('button', { name: 'Switch' }));
    await waitFor(() => expect(onSwitched).toHaveBeenCalled());
    expect(switchSource).toHaveBeenCalledWith('s1', 'https://arena.ai/blog/feed.xml', undefined);
    expect(screen.queryByText('This source stopped working.')).not.toBeInTheDocument();
  });

  it('Switch to a page follows it under its prefix', async () => {
    const switchSource = vi.fn().mockResolvedValue({ success: true });
    setup(broken({ replacement: page }), { switchSource });
    fireEvent.click(screen.getByRole('button', { name: 'Switch' }));
    await waitFor(() => expect(switchSource).toHaveBeenCalledWith('s1', 'https://arena.ai/blog/', { prefix: '/blog/' }));
  });

  it('Dismiss hides it without switching', async () => {
    const dismissReplacement = vi.fn().mockResolvedValue({ success: true, row: broken() });
    const { onSwitched } = setup(broken({ replacement: feed }), { dismissReplacement });
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByText('This source stopped working.')).not.toBeInTheDocument());
    expect(dismissReplacement).toHaveBeenCalledWith('s1');
    expect(onSwitched).not.toHaveBeenCalled();
  });

  it('a failed switch says why and keeps the offer', async () => {
    const switchSource = vi.fn().mockRejectedValue(new Error('https://arena.ai/blog/feed.xml is already a source'));
    setup(broken({ replacement: feed }), { switchSource });
    fireEvent.click(screen.getByRole('button', { name: 'Switch' }));
    expect(await screen.findByText(/is already a source/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Switch' })).toBeEnabled();
  });

  it('says when it looked and found nothing', () => {
    setup(broken({ replacement: null }));
    expect(screen.getByText('INSIGHT looked for a replacement 2h ago and found none.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Switch' })).not.toBeInTheDocument();
  });

  it('shows nothing before the doctor looked', () => {
    setup(broken({ doctor_looked_at: null, replacement: null }));
    expect(screen.queryByText('This source stopped working.')).not.toBeInTheDocument();
  });
});
