import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';

import Connected from './Connected';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { ConnectedRow, PostConnectedSeries, PostSeries, SeriesPart } from '../../services/api';

// The Series line above Connected (issue 0134): "Part 3 of 4 in <name>", the stored parts, prev / next; a column's
// issue and the previous one; series navigation links shown there, not as Earlier rows.

const id = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;
const POST = id(3);

function part(n: number, overrides: Partial<SeriesPart> = {}): SeriesPart {
  return { post_id: id(n), number: String(n), position: n - 1, title: `The report, part ${n}`,
    date: `2026-10-0${n}T08:00:00+00:00`, current: n === 3, ...overrides };
}

function series(overrides: Partial<PostSeries> = {}): PostSeries {
  const parts = [part(2), part(3), part(4)];
  return { id: 's1', kind: 'series', name: 'The report', number: '3', position: 2, count: 3, total: 4, parts,
    prev: parts[0], next: parts[2], ...overrides };
}

function row(overrides: Partial<ConnectedRow> = {}): ConnectedRow {
  return { post_id: id(5), url: 'https://writer.test/5', source: 'A writer', source_id: 's', date: '2026-09-01T08:00:00+00:00',
    title: 'How the planner works', same_source: true, reason: null, reason_kind: null, ...overrides };
}

function answer(overrides: Partial<PostConnectedSeries> = {}): PostConnectedSeries {
  return { success: true, earlier: [], later: [], outside: [], more: { earlier: 0, later: 0, outside: 0 }, series: series(),
    navigation: [], ...overrides };
}

function renderIt(data: PostConnectedSeries) {
  const getPostConnected = vi.fn().mockResolvedValue(data);
  renderWithProviders(<Connected postId={POST} />, { api: makeFakeApi({ getPostConnected }), route: `/posts/${POST}` });
  return getPostConnected;
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

describe('the Series line (issue 0134)', () => {
  it('says "Part 3 of 4 in <name>", lists the stored parts in order, with prev and next', async () => {
    renderIt(answer());
    const line = await screen.findByLabelText('Series');
    expect(line).toHaveTextContent('Part 3 of 4 in The report');
    const nav = within(line).getByRole('navigation', { name: 'Series navigation' });
    expect(within(nav).getByRole('link', { name: '‹ Previous part' })).toHaveAttribute('href', `/posts/${id(2)}`);
    expect(within(nav).getByRole('link', { name: 'Next part ›' })).toHaveAttribute('href', `/posts/${id(4)}`);
    const parts = within(within(line).getByRole('group', { name: 'Parts' })).getAllByRole('listitem');
    expect(parts.map((p) => p.textContent?.slice(0, 2))).toEqual(['2.', '3.', '4.']);
    expect(within(parts[1]).queryByRole('link')).toBeNull();   // this post: no link to itself
    expect(parts[1].querySelector('[aria-current]')).toHaveTextContent('The report, part 3');
    // no Earlier / Later rows: no "Connected" heading
    expect(screen.queryByText('Connected')).toBeNull();
  });

  it('a column: "Issue #136 of <name>" and the previous issue, no parts list', async () => {
    const prev = part(2, { number: '135', title: 'Digest #135' });
    renderIt(answer({ series: series({ kind: 'column', name: 'Digest', number: '136', parts: [prev], prev, next: null }) }));
    const line = await screen.findByLabelText('Series');
    expect(line).toHaveTextContent('Issue #136 of Digest');
    expect(within(line).getByRole('link', { name: '‹ Previous issue' })).toHaveAttribute('href', `/posts/${id(2)}`);
    expect(within(line).queryByRole('link', { name: /Next/ })).toBeNull();
    expect(within(line).queryByRole('group', { name: 'Parts' })).toBeNull();
  });

  it('navigation links show under the line, not as Earlier rows; the parts already listed once', async () => {
    renderIt(answer({
      earlier: [row({ post_id: id(7), source: 'Another writer', same_source: false, title: 'Their take' })],
      navigation: [{ ...row(), group: 'earlier' }, { ...row({ post_id: id(4), title: 'The report, part 4' }), group: 'later' }],
    }));
    const line = await screen.findByLabelText('Series');
    const links = within(line).getByLabelText('Series links');
    expect(within(links).getAllByRole('listitem')).toHaveLength(1);   // part 4 is in the parts list already
    expect(within(links).getByRole('link', { name: 'How the planner works' })).toHaveAttribute('href', `/posts/${id(5)}`);
    const earlier = screen.getByRole('group', { name: /Earlier/ });
    expect(within(earlier).getAllByRole('listitem')).toHaveLength(1);
    expect(earlier).toHaveTextContent('Their take');
    expect(screen.getByText('Connected')).toBeInTheDocument();
  });

  it('navigation links with no series still show, as Series links', async () => {
    renderIt(answer({ series: null, navigation: [{ ...row(), group: 'earlier' }] }));
    const line = await screen.findByLabelText('Series');
    expect(within(line).getByText('Series links')).toBeInTheDocument();
    expect(line).not.toHaveTextContent(/Part \d/);
  });

  it('an older server (no series keys) shows Connected as before, and nothing for no rows', async () => {
    const get = renderIt({ success: true, earlier: [], later: [], outside: [], more: { earlier: 0, later: 0, outside: 0 } });
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'Connected' })).toBeNull();
  });

  it('on a phone the parts fold, prev / next stay; on a wider screen they are open', async () => {
    phone(true);
    renderIt(answer());
    const line = await screen.findByLabelText('Series');
    expect((within(line).getByRole('group', { name: 'Parts' }) as HTMLDetailsElement).open).toBe(false);
    expect(within(line).getByRole('link', { name: 'Next part ›' })).toBeVisible();
  });

  it('a part with no number shows its position', async () => {
    renderIt(answer({ series: series({ number: null, position: 1, total: 3 }) }));
    expect(await screen.findByLabelText('Series')).toHaveTextContent('Part 1 of 3 in The report');
  });
});
