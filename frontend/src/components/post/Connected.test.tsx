import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import Connected from './Connected';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { ConnectedRow, PostConnected } from '../../services/api';

// Connected on every post (issue 0125): Earlier, Later and Outside INSIGHT, the author's own links, no model.

const POST = '00000000-0000-4000-8000-000000000001';
const PART_ONE = '00000000-0000-4000-8000-000000000002';
const THEIRS = '00000000-0000-4000-8000-000000000003';
const REPLY = '00000000-0000-4000-8000-000000000004';

function stored(overrides: Partial<ConnectedRow>): ConnectedRow {
  return {
    post_id: PART_ONE, url: 'https://writer.test/part-one', source: 'A writer', source_id: 's1', date: '2026-10-20T08:00:00+00:00',
    title: 'Part one: the scheduler', same_source: true, reason: 'Part one: the scheduler', reason_kind: 'title', ...overrides,
  };
}

function outside(overrides: Partial<ConnectedRow> = {}): ConnectedRow {
  return {
    post_id: null, url: 'https://report.test/2026/the-report?gift=1', address: 'https://report.test/2026/the-report',
    host: 'report.test', source: null, date: null, title: 'the report', same_source: false,
    reason: 'The report everyone cites came out this week and is worth reading: the report', reason_kind: 'sentence', ...overrides,
  };
}

function answer(overrides: Partial<PostConnected> = {}): PostConnected {
  return {
    success: true,
    earlier: [
      stored({}),
      stored({ post_id: THEIRS, url: 'https://other.test/take', source: 'Another writer', same_source: false,
        title: 'Their take on schedulers', reason: 'They explain why in a long thread, with numbers.', reason_kind: 'sentence' }),
    ],
    later: [stored({ post_id: REPLY, source: 'Another writer', same_source: false, title: 'A reply to part two',
      date: '2026-11-02T08:00:00+00:00', reason: 'A reply to part two', reason_kind: 'title' })],
    outside: [outside(), outside({ url: 'https://docs.test/guide', address: 'https://docs.test/guide', host: 'docs.test',
      title: 'Why Schedulers Drop Tasks', reason: null, reason_kind: null })],
    more: { earlier: 0, later: 0, outside: 0 },
    ...overrides,
  };
}

function renderConnected(getPostConnected: ReturnType<typeof vi.fn>) {
  return renderWithProviders(<Connected postId={POST} />, { api: makeFakeApi({ getPostConnected }), route: `/posts/${POST}` });
}

function phone(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: matches && query.includes('max-width'), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

afterEach(() => {
  // @ts-expect-error jsdom has none; a test may set one
  delete window.matchMedia;
});

describe('Connected (issue 0125)', () => {
  it('lists Earlier, Later and Outside INSIGHT, each row with its source, title and the author\'s reason', async () => {
    renderConnected(vi.fn().mockResolvedValue(answer()));
    const block = await screen.findByRole('region', { name: 'Connected' });
    const earlier = within(block).getByRole('group', { name: /Earlier/ });
    const rows = within(earlier).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(/A writer.*Part one: the scheduler.*same source/);
    expect(within(rows[0]).getByRole('link', { name: 'Part one: the scheduler' })).toHaveAttribute('href', `/posts/${PART_ONE}`);
    // The title is the row: a reason that only repeats it is not shown again.
    expect(rows[0].querySelector('q')).toBeNull();
    expect(rows[1]).toHaveTextContent('Another writer');
    expect(rows[1]).not.toHaveTextContent('same source');
    expect(rows[1].querySelector('q')).toHaveTextContent('They explain why in a long thread, with numbers.');

    const later = within(block).getByRole('group', { name: /Later/ });
    expect(within(later).getByRole('link', { name: 'A reply to part two' })).toHaveAttribute('href', `/posts/${REPLY}`);

    const out = within(block).getByRole('group', { name: /Outside INSIGHT/ });
    const pages = within(out).getAllByRole('listitem');
    expect(pages[0]).toHaveTextContent('report.test');
    const page = within(pages[0]).getByRole('link', { name: 'the report' });
    expect(page).toHaveAttribute('href', 'https://report.test/2026/the-report?gift=1');
    expect(page).toHaveAttribute('target', '_blank');
    expect(pages[0].querySelector('q')).toHaveTextContent(/^The report everyone cites/);
    // Save any page fetches the source that owns it, on a click (issue 0122): nothing is fetched by itself.
    expect(within(pages[0]).getByRole('link', { name: /Save/ }).getAttribute('href')).toMatch(/^\/save\?url=https%3A%2F%2Freport\.test/);
    expect(pages[1].querySelector('q')).toBeNull();
  });

  it('says how many more each group has, and opens the full list', async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 10 }, (_, n) => stored({ post_id: `00000000-0000-4000-8000-0000000001${String(n).padStart(2, '0')}`, title: `Part ${n}` }));
    const get = vi.fn()
      .mockResolvedValueOnce(answer({ earlier: many, later: [], outside: [], more: { earlier: 3, later: 0, outside: 0 } }))
      .mockResolvedValueOnce(answer({ earlier: [...many, stored({ post_id: THEIRS, title: 'Part 10' }), stored({ post_id: REPLY, title: 'Part 11' }),
        stored({ post_id: POST.replace(/1$/, '9'), title: 'Part 12' })], later: [], outside: [], more: { earlier: 0, later: 0, outside: 0 } }));
    renderConnected(get);
    const block = await screen.findByRole('region', { name: 'Connected' });
    expect(within(block).queryByRole('group', { name: /Later/ })).toBeNull();
    await user.click(within(block).getByRole('button', { name: '+3 more' }));
    await waitFor(() => expect(within(block).getAllByRole('listitem')).toHaveLength(13));
    expect(get).toHaveBeenLastCalledWith(POST, true);
    expect(within(block).queryByRole('button', { name: /more/ })).toBeNull();
  });

  it('shows nothing for a post with no connection, and nothing while it loads or when it fails', async () => {
    const empty = vi.fn().mockResolvedValue(answer({ earlier: [], later: [], outside: [] }));
    const { unmount } = renderConnected(empty);
    await waitFor(() => expect(empty).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'Connected' })).toBeNull();
    unmount();
    const failing = vi.fn().mockRejectedValue(new Error('down'));
    renderConnected(failing);
    await waitFor(() => expect(failing).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'Connected' })).toBeNull();
  });

  it('on a phone the groups fold, Earlier open', async () => {
    phone(true);
    renderConnected(vi.fn().mockResolvedValue(answer()));
    const block = await screen.findByRole('region', { name: 'Connected' });
    const open = (name: RegExp) => (within(block).getByRole('group', { name }) as HTMLDetailsElement).open;
    expect([open(/Earlier/), open(/Later/), open(/Outside/)]).toEqual([true, false, false]);
  });

  it('on a wider screen every group is open', async () => {
    phone(false);
    renderConnected(vi.fn().mockResolvedValue(answer()));
    const block = await screen.findByRole('region', { name: 'Connected' });
    const open = (name: RegExp) => (within(block).getByRole('group', { name }) as HTMLDetailsElement).open;
    expect([open(/Earlier/), open(/Later/), open(/Outside/)]).toEqual([true, true, true]);
  });
});
