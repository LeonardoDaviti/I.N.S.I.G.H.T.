import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';

import FeedGroup from './FeedGroup';
import { feedItem } from './fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { FeedGroup as FeedGroupData } from '../../services/api';

const SOURCE = '0a5e90ae-2533-4a31-bf0a-cafd414fc0ce';

function group(count: number, n = 3): FeedGroupData {
  const items = Array.from({ length: n }, (_, i) => feedItem({
    id: `00000000-0000-4000-8000-00000000010${i}`,
    title: `Post ${i + 1}`,
    source_id: SOURCE,
    source_display_name: 'cs.CL',
  }));
  return { source_id: SOURCE, source_display_name: 'cs.CL', platform: 'rss', newest_sort_at: items[0].sort_at, count, items };
}

function renderGroup(data: FeedGroupData) {
  return renderWithProviders(
    <FeedGroup
      group={data}
      selectedId={null}
      itemHref={(item) => `/posts/${item.id}`}
      onSelect={vi.fn()}
      onOpen={vi.fn()}
      onToggleRead={vi.fn()}
      onToggleStar={vi.fn()}
      onToggleLater={vi.fn()}
    />,
    { api: makeFakeApi({}) },
  );
}

describe('FeedGroup', () => {
  it('renders at most 3 items plus "N more from <source>" linking to the source scope', () => {
    renderGroup(group(40));
    expect(screen.getAllByRole('article')).toHaveLength(3);
    const more = screen.getByRole('link', { name: '37 more from cs.CL' });
    expect(more).toHaveAttribute('href', `/read/source/${SOURCE}`);
    const heading = screen.getByRole('heading', { name: /cs\.CL/ });
    expect(within(heading).getByRole('link')).toHaveAttribute('href', `/read/source/${SOURCE}`);
  });

  it('shows no "more" link when every post is shown, and pluralizes the count', () => {
    renderGroup(group(1, 1));
    expect(screen.queryByRole('link', { name: /more from/ })).not.toBeInTheDocument();
    expect(screen.getByText('1 post')).toBeInTheDocument();
  });

  it('formats huge counts', () => {
    renderGroup(group(12_847));
    expect(screen.getByRole('link', { name: '12,844 more from cs.CL' })).toBeInTheDocument();
  });

  it('never claims fewer posts than it shows (a stale count of 0 above 3 posts)', () => {
    renderGroup(group(0, 3));
    expect(screen.getByText('3 posts')).toBeInTheDocument();
    expect(screen.queryByText('0 posts')).not.toBeInTheDocument();
  });

  it('keeps the date column (no day header above a group)', () => {
    const data = group(3, 1);
    const old = new Date(Date.now() - 12 * 24 * 3_600_000);
    data.items[0] = { ...data.items[0], sort_at: old.toISOString(), published_at: old.toISOString() };
    renderGroup(data);
    const shortDate = old.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    expect(within(screen.getByRole('article')).getByText(shortDate)).toBeInTheDocument();
  });
});
