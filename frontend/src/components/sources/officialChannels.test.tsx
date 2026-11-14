import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import OfficialChannels from './OfficialChannels';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { OfficialResponse, OfficialRow } from '../../services/api';
import { filterLine, fromLine, groupRows, judgeLine, kindLabel, modeLine, proofLine } from '../../lib/official';

const base: OfficialRow = {
  id: 'o1', key: 'acme.example/blog/', kind: 'section', state: 'added',
  why: 'Acme announced Widget 5 on its own blog', actor: { id: 'e1', name: 'Acme' },
  follow: 'https://acme.example/blog/', from: 'own_page', owned: 'on acme.example, Acme’s own site',
  proof: { via: 'feed', address: 'https://acme.example/blog/feed', items: 20, dated: 12, holds: 2, linked: 3, newest_days: 1 },
  judge: { verdict: 'follow', fits: true, original: 'yes', reasons: ['posts its own releases', 'fits AI news', 'third reason'] },
  filter: { kind: 'regex', hide: [{ field: 'title', regex: '^Hiring', why: 'job posts' }] },
  source_id: 'src1', hidden_items: 3,
  events: [
    { story: 's1', headline: 'Acme ships Widget 5', voices: 3, first_at: null },
    { story: 's2', headline: 'Acme opens a lab', voices: 2, first_at: null },
    { story: 's3', headline: 'A third event', voices: 2, first_at: null },
  ],
  decided_at: null, created_at: null,
};
const row = (over: Partial<OfficialRow>): OfficialRow => ({ ...base, ...over });
const rows: OfficialRow[] = [
  row({ id: 'r1', key: 'x.com/acme-refused', kind: 'x', state: 'refused', follow: null, filter: null, judge: null, proof: null }),
  row({ id: 'u1', key: 'x.com/acme-undone', kind: 'x', state: 'undone' }),
  row({ id: 'c1', key: 'acme.example/news/', state: 'covered' }),
  row({ id: 'w1', key: 't.me/acme', kind: 'telegram', state: 'would_add' }),
  row({ id: 'p1', key: 'github.com/acme/widget', kind: 'releases', state: 'proven', from: 'code_address' }),
  row({ id: 'a1', key: 'acme.example/blog/', state: 'added' }),
];

function answer(list: OfficialRow[], over: Partial<OfficialResponse> = {}): OfficialResponse {
  return { success: true, mode: 'on', cap: 5, added_today: 1, counts: {}, events: {}, rows: list, ...over };
}

function setup(list: OfficialRow[], api: Record<string, unknown> = {}) {
  const getOfficial = vi.fn().mockResolvedValue(answer(list));
  renderWithProviders(<OfficialChannels />, { api: makeFakeApi({ getOfficial, ...api }) });
  return { getOfficial };
}

describe('OfficialChannels (issue 0196)', () => {
  it('groups the rows in order; refused, undone and already followed start collapsed', async () => {
    setup(rows);
    const section = await screen.findByRole('region', { name: 'Official channels' });
    expect(within(section).getByText(/^On: official channels are added automatically, at most 5 a day \(1 today\)$/))
      .toBeInTheDocument();
    const titles = within(section).getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(['Added automatically', 'Would add', 'Being checked', 'Already followed', 'Refused', 'Undone']);
    expect(screen.getByRole('link', { name: 'acme.example/blog/' })).toHaveAttribute('href', 'https://acme.example/blog/');
    expect(screen.getByText('t.me/acme')).toBeInTheDocument();
    expect(screen.getByText('github.com/acme/widget')).toBeInTheDocument();
    expect(screen.queryByText('x.com/acme-refused')).not.toBeInTheDocument();
    expect(screen.queryByText('x.com/acme-undone')).not.toBeInTheDocument();
    expect(screen.queryByText('acme.example/news/')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show 1 refused' }));
    expect(screen.getByText('x.com/acme-refused')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show 1 undone' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show 1 already followed' })).toBeInTheDocument();
  });

  it('says what was found, from where, how it was checked and what it hides; two events at most', async () => {
    setup([base]);
    expect(await screen.findByText('Acme announced Widget 5 on its own blog')).toBeInTheDocument();
    expect(screen.getByText('Found from its own page in a story')).toBeInTheDocument();
    expect(screen.getByText('on acme.example, Acme’s own site')).toBeInTheDocument();
    expect(screen.getByText("12 dated items read via feed; holds 2 of the event's pages")).toBeInTheDocument();
    expect(screen.getByText('Worker: follow · fits your topics: yes · posts its own releases; fits AI news')).toBeInTheDocument();
    expect(screen.getByText('Hides: job posts (^Hiring) · 3 hidden')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Acme ships Widget 5' })).toHaveAttribute('href', '/markx/stories/s1');
    expect(screen.getByRole('link', { name: 'Acme opens a lab' })).toBeInTheDocument();
    expect(screen.queryByText('A third event')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Acme' })).toHaveAttribute('href', '/markx/entities/e1');
  });

  it('Undo is only on rows added automatically, and calls the api', async () => {
    let finish: (value: unknown) => void = () => {};
    const undoOfficial = vi.fn().mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const { getOfficial } = setup(rows.filter((r) => r.state !== 'refused'), { undoOfficial });
    await screen.findByRole('region', { name: 'Official channels' });
    fireEvent.click(screen.getByRole('button', { name: 'Show 1 undone' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show 1 already followed' }));
    expect(screen.getAllByRole('button', { name: 'Undo' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(undoOfficial).toHaveBeenCalledWith('a1'));
    expect(await screen.findByRole('button', { name: 'Undoing…' })).toBeDisabled();
    finish({ success: true, id: 'a1', state: 'undone', source_id: 'src1' });
    await waitFor(() => expect(getOfficial).toHaveBeenCalledTimes(2));
  });

  it('shows nothing when there are no rows', async () => {
    const { getOfficial } = setup([]);
    await waitFor(() => expect(getOfficial).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'Official channels' })).not.toBeInTheDocument();
  });

  it('says each line plainly', () => {
    expect(modeLine({ mode: 'shadow', cap: 5, added_today: 0 })).toBe('Shadow: nothing is added, it shows what would be');
    expect(modeLine({ mode: 'off', cap: 5, added_today: 0 })).toBe('Off');
    expect(kindLabel('x')).toBe('X account');
    expect(kindLabel('telegram')).toBe('Telegram channel');
    expect(kindLabel('youtube')).toBe('YouTube channel');
    expect(kindLabel('section')).toBe('site section');
    expect(kindLabel('releases')).toBe('releases');
    expect(fromLine('code_address')).toBe('Found from its code repository');
    expect(fromLine('handle')).toBe('Found from its handle');
    expect(fromLine('web_search')).toBe('Found from a web search');
    expect(fromLine('web_announcement')).toBe('Found from the announcement the web search found');
    expect(fromLine(null)).toBeNull();
    expect(proofLine(null)).toBeNull();
    expect(proofLine({ ...base.proof!, dated: 1, via: 'page watching', holds: 0 }))
      .toBe("1 dated item read via page watching; holds 0 of the event's pages");
    expect(judgeLine({ verdict: 'skip', fits: false, original: null, reasons: [] })).toBe('Worker: skip · fits your topics: no');
    expect(judgeLine(null)).toBeNull();
    expect(filterLine(null, 0)).toBeNull();
    expect(groupRows(rows).map((g) => g.group.id)).toEqual(['added', 'would_add', 'checking', 'covered', 'refused', 'undone']);
  });
});
