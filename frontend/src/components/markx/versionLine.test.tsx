import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';

import { ThingLinks, VersionLine } from './MarkXTimeline';
import type { MarkxEntityRelation, MarkxVersionLine } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const api = makeFakeApi({});

/** Issue 0220, invented names: a family's versions on one line, and the relations posts state between things. */
const LINE: MarkxVersionLine = {
  family: { id: 'fam', name: 'Orbit' },
  lines: [
    [
      { id: 'o2', name: 'Orbit 2', version: '2', first: '2026-03-02T10:00:00Z', posts: 40, current: false },
      { id: 'o25', name: 'Orbit 2.5', version: '2.5', first: '2026-07-14T10:00:00Z', posts: 12, current: true },
      { id: 'o3', name: 'Orbit 3', version: '3', first: null, posts: 5, current: false },
    ],
    [
      { id: 'r1', name: 'Orbit R1', version: 'R1', first: '2026-01-20T00:00:00Z', posts: 9, current: false },
      { id: 'r2', name: 'Orbit R2', version: 'R2', first: '2026-09-01T00:00:00Z', posts: 6, current: false },
    ],
  ],
};

const rel = (relation: MarkxEntityRelation['relation'], direction: MarkxEntityRelation['direction'], id: string,
  name: string, posts = 1): MarkxEntityRelation => ({
  relation, direction, other: { id, name, type: 'model' }, since: '2026-10-02T00:00:00Z', posts,
});

describe('the version line (0220)', () => {
  it('shows each line oldest version first, the page\'s own version marked, the others as links', () => {
    renderWithProviders(<VersionLine line={LINE} />, { api });
    const section = screen.getByRole('region', { name: 'Version line' });
    const lines = within(section).getAllByRole('list');
    expect(lines).toHaveLength(2);
    const stops = within(lines[0]).getAllByRole('listitem');
    expect(stops.map((s) => s.textContent)).toEqual(['Orbit 2 · 2026-03', '→ Orbit 2.5 · 2026-07', '→ Orbit 3']);
    expect(within(stops[1]).queryByRole('link')).toBeNull();                       // its own version: no link
    expect(within(stops[1]).getByText('Orbit 2.5')).toHaveAttribute('aria-current', 'true');
    expect(within(stops[0]).getByRole('link', { name: 'Orbit 2' })).toHaveAttribute('href', '/markx/entities/o2');
    expect(within(lines[1]).getAllByRole('listitem').map((s) => s.textContent)).toEqual(['Orbit R1 · 2026-01', '→ Orbit R2 · 2026-09']);
  });
});

describe('the relations between things (0220)', () => {
  it('words each relation by its direction and groups the other things', () => {
    renderWithProviders(<ThingLinks relations={[rel('based_on', 'in', 's2', 'Sabi 2', 3), rel('based_on', 'in', 'k1', 'Kestrel 1'),
      rel('released', 'in', 'v', 'Vantor', 2), rel('based_on', 'out', 'o3', 'Orbit 3'), rel('released', 'out', 'w', 'Widget')]} />,
    { api });
    const section = screen.getByRole('region', { name: 'Links' });
    const rows = within(section).getAllByRole('listitem');
    expect(rows.map((r) => r.textContent)).toEqual(['Built on it: Sabi 2 (3 posts), Kestrel 1 (1 post)',
      'Released by: Vantor (2 posts)', 'Based on: Orbit 3 (1 post)', 'Released: Widget (1 post)']);
    expect(within(rows[0]).getByRole('link', { name: 'Sabi 2' })).toHaveAttribute('href', '/markx/entities/s2');
  });

  it('shows nothing without relations', () => {
    const { container } = renderWithProviders(<ThingLinks relations={[]} />, { api });
    expect(container.textContent).toBe('');
  });
});
