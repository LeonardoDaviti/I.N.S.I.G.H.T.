import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';

import FeedItem from './FeedItem';
import type { FeedItem as Item } from '../../services/api';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

// v10.47: a page that states only its month and year ("February 2026") is stored as the 1st, precision "month"
const item = (precision: string | null): Item => ({
  id: 'p1', title: 'The Hot Mess of AI', excerpt: '', url: 'https://lab.example/2026/hot-mess/',
  source_id: 's1', source_display_name: 'Lab Blog', platform: 'rss',
  sort_at: '2026-02-01T00:00:00+00:00', published_at: '2026-02-01T00:00:00+00:00', published_precision: precision,
  read_at: null, starred_at: null, reading_minutes: 3, duration_seconds: null, media_thumb: null,
} as Item);

const row = (precision: string | null) => renderWithProviders(
  <FeedItem item={item(precision)} selected={false} tabbable href="/posts/p1" onSelect={vi.fn()} onOpen={vi.fn()}
    onToggleRead={vi.fn()} onToggleStar={vi.fn()} onToggleLater={vi.fn()} now={new Date('2026-11-24T10:00:00Z')} />,
  { api: makeFakeApi({}) },
);

describe('a month-precise post (v10.47)', () => {
  it('shows its month alone, never a day the page does not state', () => {
    row('month');
    expect(screen.getAllByText('Feb 2026').length).toBeGreaterThan(0);
    expect(screen.queryByText(/Feb 1/)).not.toBeInTheDocument();
  });

  it('a day-precise post on the same instant still shows its day', () => {
    row('date');
    expect(screen.getAllByText(/Feb 1/).length).toBeGreaterThan(0);
    expect(screen.queryByText('Feb 2026')).not.toBeInTheDocument();
  });
});
