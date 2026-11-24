import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import NeedsAttention, { AttentionLine } from './NeedsAttention';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { AttentionResponse } from '../../services/api';

const answer: AttentionResponse = {
  computed_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  count: 2,
  line: 'Needs attention (2): Feeds: bridge.example answers 502; Every bridge_rss source fails',
  items: [
    { key: 'platform:bridge_rss', kind: 'platform', level: 'act', title: 'Every bridge_rss source fails', detail: '3 of 3 failed' },
    { key: 'source:s1', kind: 'source', level: 'act', title: 'Feeds', detail: 'bridge.example answers 502; 4 failures in a row', source_id: 's1' },
    { key: 'silent:s2', kind: 'silent', level: 'watch', title: 'Quiet blog', detail: 'no post in 40 days', source_id: 's2' },
    { key: 'db_size', kind: 'db_size', level: 'info', title: 'Database 50.0 GB', detail: 'kept everything' },
  ],
};

function setup(response: AttentionResponse | Error = answer) {
  const getAttention = response instanceof Error ? vi.fn().mockRejectedValue(response) : vi.fn().mockResolvedValue(response);
  const onOpenSource = vi.fn();
  renderWithProviders(
    <><AttentionLine /><NeedsAttention titleClass="" onOpenSource={onOpenSource} /></>,
    { api: makeFakeApi({ getAttention }) },
  );
  return { onOpenSource };
}

describe('Needs attention', () => {
  it('counts what to act on, lists what to watch apart, and opens a source', async () => {
    const { onOpenSource } = setup();
    const now = await screen.findByRole('list', { name: 'Needs attention now' });
    expect(within(now).getAllByRole('listitem').map((li) => li.getAttribute('data-attention')))
      .toEqual(['platform:bridge_rss', 'source:s1']);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('1 to watch')).toBeInTheDocument();
    expect(screen.getByText(/Database 50.0 GB/)).toBeInTheDocument();
    await userEvent.click(within(now).getByRole('button', { name: 'Feeds' }));
    expect(onOpenSource).toHaveBeenCalledWith('s1');
    expect(screen.getByRole('link', { name: answer.line as string })).toHaveAttribute('href', '/settings/sources?tab=ingestion');
  });

  it('says when it has not checked yet, and nothing when nothing needs attention', async () => {
    setup({ computed_at: null, count: 0, items: [], line: null });
    expect(await screen.findByText(/Not checked yet/)).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('says when it cannot be read', async () => {
    setup(new Error('500'));
    expect(await screen.findByText('Could not read what needs attention.')).toBeInTheDocument();
  });
});
