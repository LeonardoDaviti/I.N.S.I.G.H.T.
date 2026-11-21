import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import PeopleAndMakers, { followAddress } from './PeopleAndMakers';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { PeopleResponse, PeopleRow } from '../../services/api';

const author: PeopleRow = {
  key: 'x.com/janedoe', kind: 'author', platform: 'x', name: 'janedoe', posts: 4, sources: 2,
  accounts: ['x.com/janedoe'], tracks: ['Agentic Workflows'], news: 1, how: { quote: 3, repost: 1 },
  why: '4 of your posts in 30 days in Agentic Workflows and News (1)',
  evidence: [{ post_id: 'p1', title: 'A hands-on test of an agent', url: 'https://example.org/p1', where: 'track:Agentic Workflows', how: 'quote', at: null }],
  follow: { address: 'https://x.com/janedoe', via: 'x bridge', feed: 'https://bridge.local/janedoe/rss', ready: true },
};
const maker: PeopleRow = {
  ...author, key: 'maker:m1', kind: 'maker', platform: 'maker', name: 'Acme Labs', accounts: [], follow: null,
  channels: [], evidence: [],
};

function setup(answer: Partial<PeopleResponse>) {
  const onFollow = vi.fn();
  const getDiscoverPeople = vi.fn().mockResolvedValue({
    window_days: 30, posts: 10, authors: [], makers: [], built_at: null, refreshing: false, ...answer,
  });
  renderWithProviders(<PeopleAndMakers onFollow={onFollow} />, { api: makeFakeApi({ getDiscoverPeople }) });
  return { onFollow, getDiscoverPeople };
}

describe('PeopleAndMakers (issue 0276)', () => {
  it('shows each row, follows through Add source and opens the posts', async () => {
    const { onFollow } = setup({ authors: [author], makers: [maker] });
    expect(await screen.findByRole('heading', { name: 'People and makers your tracks quote' })).toBeInTheDocument();
    expect(screen.getByText(/x · 4 posts · Agentic Workflows, News/)).toBeInTheDocument();
    expect(screen.getByText('Its own channels are not found yet')).toBeInTheDocument();
    const follows = screen.getAllByRole('button', { name: 'Follow…' });
    expect(follows).toHaveLength(1);                       // a maker with no channel has none
    fireEvent.click(follows[0]);
    expect(onFollow).toHaveBeenCalledWith('https://x.com/janedoe');
    expect(screen.queryByText('A hands-on test of an agent')).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: /The posts that brought/ })[0]);
    expect(screen.getByText('A hands-on test of an agent')).toBeInTheDocument();
    expect(screen.getByText('· Agentic Workflows · quote')).toBeInTheDocument();
  });

  it('shows nothing when empty', async () => {
    const { getDiscoverPeople } = setup({});
    await waitFor(() => expect(getDiscoverPeople).toHaveBeenCalled());
    expect(screen.queryByRole('heading', { name: 'People and makers your tracks quote' })).not.toBeInTheDocument();
  });

  it('a maker follows its first official channel', () => {
    expect(followAddress({ ...maker, channels: [{ key: 'x.com/acme', kind: 'x', state: 'would_add', address: 'https://x.com/acme', source_id: null }] }))
      .toBe('https://x.com/acme');
    expect(followAddress(maker)).toBeNull();
  });
});
