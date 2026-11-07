import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import MarkXStoryPage from '../../pages/MarkXStoryPage';
import { PerspectiveAccuracy } from './MarkXPerspectives';
import type { MarkxPerspectiveAccuracy, MarkxPerspectiveLine, MarkxStoryView } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const now = new Date().toISOString();
const line = (post: string, label: MarkxPerspectiveLine['label'], extra: Partial<MarkxPerspectiveLine> = {}): MarkxPerspectiveLine => ({
  post, member: true, label, sign: label ? { original: '★', new_facts: '+', opinion: '~', same: '=', not_this_story: '×' }[label] : null,
  by: 'haiku', worth: label ? ['original', 'new_facts', 'opinion'].includes(label) : null, before: false, point: null,
  claims: [], copies: [], facts: [], mine: null, ...extra,
});
const post = (id: string, title: string, source: string) => ({ id, title, source, kind: 'telegram', at: now, url: null });
const VIEW: MarkxStoryView = {
  story: { id: 's1', headline: 'Acme releases Nimbus 5', first_at: now },
  judged: true,
  header: { text: 'Experimental: on unseen stories about 83% right on worth opening, 62% on new facts (lab, 2026-11-05).',
    source: 'lab', labels: 0 },
  sheet: {
    subject: 'Nimbus 5 is out',
    original: { post: 'p1', is_original: true, title: 'We release Nimbus 5', source: 'Acme', at: now, text: 'Today we release', also: [] },
    source_page: null,
    new_facts: [{ fact: '81% on the coding set', posts: ['p2'], sources: ['Example Lab'], correction: false, before: false, lines: [1] },
      { fact: 'output $5 per million, not $2 as first reported', posts: ['p3', 'p2'], sources: ['Example Wire', 'Example Lab'],
        correction: true, before: false, lines: [2, 3] }],
    before: { facts: [], claims: [] },
    claims: [{ claim: 'a bigger one soon', post: 'p2', source: 'Example Lab' }],
    opinions: [{ point: null, post: 'p4', source: 'Example Blog' }],
    same: 1, copies: 2, related: [{ post: 'p6', source: 'Example Digest', title: 'Five things this week' }], lines: 3, merged: 2,
  },
  members: [
    line('p1', 'original', { copies: ['p7', 'p8'] }),
    line('p2', 'new_facts', { facts: [{ index: 0, fact: '81% on the coding set', span: 'it scored 81 percent on the coding set',
      correction: false, mine: null }] }),
    line('p4', 'opinion', { point: 'wait for narrow benchmarks' }),
    line('p5', 'same', { by: 'code:nothing-own' }),
  ],
  counts: { members: 6, worth: 3, same: 1, copies: 2, unjudged: 0 },
  posts: { p1: post('p1', 'We release Nimbus 5', 'Acme'), p2: post('p2', 'Nimbus 5 tested', 'Example Lab'),
    p4: post('p4', 'A take on Nimbus 5', 'Example Blog'), p5: post('p5', 'Nimbus 5 is out', 'Example Channel'),
    p7: post('p7', 'We release Nimbus 5', 'Acme'), p8: post('p8', 'We release Nimbus 5', 'Acme') },
};

function renderPage(api: Parameters<typeof makeFakeApi>[0]) {
  return renderWithProviders(
    <Routes><Route path="/markx/stories/:storyId" element={<MarkXStoryPage />} /></Routes>,
    { api: makeFakeApi(api), route: '/markx/stories/s1' },
  );
}

describe('Mark X perspectives and the story sheet (issue 0119 B6-B7)', () => {
  it('shows the header, the sheet above the members, worth opening first and the rest folded', async () => {
    renderPage({ getMarkxStory: vi.fn().mockResolvedValue(VIEW) });
    expect(await screen.findByText(/about 83% right on worth opening, 62% on new facts/)).toBeInTheDocument();
    const sheet = screen.getByRole('region', { name: 'Story sheet' });
    expect(within(sheet).getByText('We release Nimbus 5')).toBeInTheDocument();
    expect(within(sheet).getByText(/output \$5 per million/).closest('li')).toHaveAttribute('data-correction', 'true');
    expect(within(sheet).getByText('an opinion without a stated point')).toBeInTheDocument();
    expect(within(sheet).getByText(/1 more says the same, plus 2 copies/)).toBeInTheDocument();
    const worth = screen.getByRole('region', { name: 'Worth opening' });
    expect(within(worth).getAllByRole('listitem').filter((li) => li.dataset.label).map((li) => li.dataset.label))
      .toEqual(['original', 'new_facts', 'opinion']);
    expect(within(worth).getByText(/2 copies folded/)).toBeInTheDocument();
    expect(screen.getByText(/1 says the same/)).toBeInTheDocument();
    expect(sheet.compareDocumentPosition(worth) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('labels a member right or wrong, the right label one tap later, and a fact with its reason', async () => {
    const labelMarkxPerspective = vi.fn()
      .mockResolvedValueOnce({ id: 'l1', answer: 'right', shown: 'original' })
      .mockResolvedValueOnce({ id: 'l2', answer: 'wrong', shown: 'opinion' })
      .mockResolvedValueOnce({ id: 'l3', answer: 'same', shown: 'opinion' });
    const labelMarkxFact = vi.fn().mockResolvedValue({ id: 'l4', answer: 'not_new' });
    renderPage({ getMarkxStory: vi.fn().mockResolvedValue(VIEW), labelMarkxPerspective, labelMarkxFact });
    const worth = await screen.findByRole('region', { name: 'Worth opening' });
    const [original, newFacts, opinion] = within(worth).getAllByRole('listitem').filter((li) => li.dataset.label);
    await userEvent.click(within(original).getByRole('button', { name: 'label right' }));
    await waitFor(() => expect(labelMarkxPerspective).toHaveBeenCalledWith('s1', 'p1', 'right'));
    expect(await within(original).findByText(/you: right/)).toBeInTheDocument();
    await userEvent.click(within(opinion).getByRole('button', { name: 'label wrong' }));
    await userEvent.click(await within(opinion).findByRole('button', { name: 'same' }));
    await waitFor(() => expect(labelMarkxPerspective).toHaveBeenLastCalledWith('s1', 'p4', 'same'));
    expect(await within(opinion).findByText(/you: it is same/)).toBeInTheDocument();
    const fact = within(newFacts).getByRole('group', { name: 'Is this a new fact?' });
    await userEvent.click(within(fact).getByRole('button', { name: 'wrong' }));
    await userEvent.click(await within(newFacts).findByRole('button', { name: 'not new' }));
    await waitFor(() => expect(labelMarkxFact).toHaveBeenCalledWith('s1', 'p2', 0, 'not_new'));
  });

  it('says when a story is not judged yet', async () => {
    renderPage({ getMarkxStory: vi.fn().mockResolvedValue({ ...VIEW, judged: false, sheet: null,
      members: [line('p1', null, { by: null })], counts: { ...VIEW.counts, worth: 0 } }) });
    expect(await screen.findByText('Not judged yet')).toBeInTheDocument();
    expect(screen.getByText('not judged yet')).toBeInTheDocument();
  });

  it('counts your labels against the lab on the Labels tab', async () => {
    const rate = (k: number, n: number) => ({ k, n, p: n ? k / n : null, lo: 0.5, hi: 0.9 });
    const acc: MarkxPerspectiveAccuracy = {
      labels: 12, fact_labels: 5, lab: { worth: 0.83, four: 0.7, new_facts: 0.62, date: '2026-11-05' },
      four: rate(9, 12), worth: rate(10, 11), new_facts: rate(3, 4), per_label: { new_facts: rate(3, 4), same: rate(2, 3) },
      facts: { ...rate(4, 5), answers: { right: 4, not_new: 1 } }, errors: { 'opinion->same': 1 }, source: 'lab', text: '',
    };
    renderWithProviders(<PerspectiveAccuracy />, { api: makeFakeApi({ getMarkxPerspectiveAccuracy: vi.fn().mockResolvedValue(acc) }) });
    const section = await screen.findByRole('region', { name: 'Perspectives' });
    expect(within(section).getByText(/12 labels on members, 5 labels on new facts/)).toBeInTheDocument();
    expect(within(section).getByText('91% (50–90), 10/11')).toBeInTheDocument();
    expect(within(section).getByText('83%')).toBeInTheDocument();
    expect(within(section).getByText(/opinion → same 1/)).toBeInTheDocument();
  });
});
