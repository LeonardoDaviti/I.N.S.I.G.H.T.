// 0162 (research, Mark X): the start page (a seed typed or passed as ?seed=), a run's page (In INSIGHT, the same
// announcement, the maker with "These are …", channels with Follow / Not this one, papers held or not, discussion,
// what could not be read), Watch this and Run again, and the lines in words. Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import ResearchPage from './ResearchPage';
import { accountLine, referencesLine, researchApi, statusLine, type ResearchPage as Data } from '../services/research';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';

const channel = (over = {}) => ({
  id: 'c1', run_id: 'sr1', track: null, finder: 'research', platform: 'site', address: 'https://acme.example/',
  key: 'acme.example', name: 'Acme AI', why: 'its profile names the other', place: 'judging' as const, reason: null,
  items: 20, judged: 0, fits: 0, precision: null, per_week: 2, cadence: '2 a week', labels: [], reads_well: true,
  follows_as: 'feed' as const, follow_address: 'https://acme.example/feed.xml', answer: null, source_id: null, fit: null, ...over,
});

const PAGE: Data = {
  run: { id: 'r1', seed_kind: 'link', seed: 'https://hub.example/acmeai/widget-1', status: 'waiting', steps: { held: 'x' },
    entity_id: 'e1', track_id: null, previous_id: null, created_at: '2026-11-12T10:00:00Z', finished_at: null,
    spent: { page_requests: 9, paper_calls: 0, search_calls: 3, identity_asked: 1, identity_open: 1, identity_pairs: 1 },
    budget: { page_requests: 60, paper_calls: 4, identity: 20, test_reads: 40, judgements: 800, web_queries: 5, discussion_searches: 6 } },
  held: [
    { key: 'entity:e1', entity: { id: 'e1', name: 'Widget One', type: 'model', maker: null }, posts: 15, stories: 3, voices: 5,
      newest: [{ post_id: 'p1', title: 'Widget One released', at: '2026-11-10T10:00:00Z', source: 'Example Channel', url: null }], new: true },
    { key: 'post:p2', post_id: 'p2', title: 'A post linking its card', source: 'Example Blog', why: 'links hub.example/acmeai/widget-1', new: true },
  ],
  same_post: [{ post_id: 'p3', title: 'Decision model to edit weights', at: null, source: 'r/examplellm', url: null,
    why: 'shares the link notebooks.example/code/x', strength: 'link', new: true }],
  entities: [{ id: 'e2', name: 'Widget One Decision', why: 'its name holds this one’s whole', new: true }],
  maker: {
    accounts: [{ key: 'hub.example/acmeai', address: 'https://hub.example/acmeai', platform: 'hub', kind: 'account',
      same: 'yes', rule: 'the platform says this account owns it', new: true }],
    asking: [{ key: 'x.com/acmeai_lab', address: 'https://x.com/acmeai_lab', platform: 'x', kind: 'account', same: 'pending', rule: 'asked Haiku' }],
    not_same: [{ key: 'x.com/acme_other', address: 'https://x.com/acme_other', platform: 'x', kind: 'account', same: 'no', rule: 'Haiku: a namesake' }],
    these_are: { entity: { id: 'e9', name: 'Acme AI' }, by: [], proposed: [{ id: 's7', name: 'Acme Blog' }] },
  },
  channels: { to_follow: [channel()], unread: [], cannot: [channel({ id: 'c2', name: 'docs.example', place: 'unreadable', reads_well: false, reason: 'blocked' })] },
  papers: {
    seed: [{ ref: 'arXiv:2606.13843', url: 'https://arxiv.org/abs/2606.13843', title: 'A study of example interfaces', date: '2026-06-11', role: 'seed', held: null }],
    reference: [{ ref: 'arXiv:2501.00001', url: null, title: 'Held ref', date: null, role: 'reference', held: 'p5' },
      { ref: 'doi:10.1145/12345', url: 'https://doi.org/10.1145/12345', title: 'Not held ref', date: null, role: 'reference', held: null }],
    citing: [], newer: [], held_references: 1, references: 2,
  },
  discussion: [{ url: 'https://forum.example/t/1', title: 'We discuss it', at: null, query: '2606.13843', why: 'contains 2606.13843', where: 'forum.example' }],
  unread: [{ key: 'page:x', url: 'https://x.com/acmeai_lab', why: 'HTTP 403' }],
};

function renderRun(route = '/research/r1') {
  return renderWithProviders(
    <Routes><Route path="/research" element={<ResearchPage />} /><Route path="/research/:runId" element={<ResearchPage />} /></Routes>,
    { api: makeFakeApi({}), route },
  );
}

afterEach(() => vi.restoreAllMocks());

describe('the lines in words', () => {
  it('says the state, an account and the references', () => {
    expect(statusLine(PAGE)).toBe('Waiting for Haiku: 1 same-maker questions (the worker’s next run) · 9 of 60 page requests · 1 identity questions');
    expect(accountLine(PAGE.maker.accounts[0])).toBe('hub.example/acmeai (hub): the platform says this account owns it');
    expect(referencesLine(PAGE.papers)).toBe('2 references: 1 in INSIGHT');
  });
});

describe('a research run (0162)', () => {
  it('shows every section', async () => {
    vi.spyOn(researchApi, 'page').mockResolvedValue(PAGE);
    renderRun();
    expect(await screen.findByRole('heading', { name: /Research: https:\/\/hub.example/ })).toBeInTheDocument();
    const held = screen.getByRole('region', { name: 'In INSIGHT' });
    expect(within(held).getByRole('link', { name: 'Widget One' })).toHaveAttribute('href', '/markx/entities/e1');
    expect(held).toHaveTextContent('15 posts · 3 stories · 5 voices');
    expect(held).toHaveTextContent('A post linking its card');
    expect(held).toHaveTextContent('Widget One Decision: may be the same thing');
    expect(screen.getByRole('region', { name: 'The same announcement elsewhere' })).toHaveTextContent('shares the link notebooks.example/code/x');
    const maker = screen.getByRole('region', { name: 'The maker' });
    expect(maker).toHaveTextContent('hub.example/acmeai (hub): the platform says this account owns it');
    expect(maker).toHaveTextContent('Not sure yet: x.com/acmeai_lab (x): asked Haiku (asking Haiku)');
    expect(maker).toHaveTextContent('Not the maker: x.com/acme_other');
    expect(maker).toHaveTextContent('These are Acme AI: Acme Blog?');
    const papers = screen.getByRole('region', { name: 'Papers' });
    expect(papers).toHaveTextContent('2 references: 1 in INSIGHT');
    expect(within(papers).getByRole('link', { name: 'Held ref' })).toHaveAttribute('href', '/posts/p5');
    expect(screen.getByRole('region', { name: 'Discussion found' })).toHaveTextContent('contains 2606.13843');
    const unread = screen.getByRole('region', { name: 'What could not be read' });
    expect(unread).toHaveTextContent("docs.example (site): can't read: blocked");
    expect(unread).toHaveTextContent('https://x.com/acmeai_lab: HTTP 403');
  });

  it('follows a channel, says not this one, answers These are, watches and runs again', async () => {
    vi.spyOn(researchApi, 'page').mockResolvedValue(PAGE);
    const follow = vi.spyOn(researchApi, 'follow').mockResolvedValue({ source_id: 's1', as: 'passive' });
    const these = vi.spyOn(researchApi, 'answerSources').mockResolvedValue({});
    const watch = vi.spyOn(researchApi, 'watch').mockResolvedValue({ track_id: 'f1', made: true });
    const rerun = vi.spyOn(researchApi, 'rerun').mockResolvedValue({ id: 'r2' });
    renderRun();
    const row = await screen.findByRole('group', { name: 'Follow Acme AI?' });
    await userEvent.click(within(row).getByRole('button', { name: 'Follow' }));
    expect(follow).toHaveBeenCalledWith('r1', 'c1');
    await userEvent.click(screen.getByRole('button', { name: 'Yes' }));
    expect(these).toHaveBeenCalledWith('e9', ['s7'], 'yes');
    await userEvent.click(screen.getByRole('button', { name: 'Watch this' }));
    expect(watch).toHaveBeenCalledWith('r1');
    await userEvent.click(screen.getByRole('button', { name: 'Run again' }));
    expect(rerun).toHaveBeenCalledWith('r1');
  });

  it('says not this one', async () => {
    vi.spyOn(researchApi, 'page').mockResolvedValue(PAGE);
    const not = vi.spyOn(researchApi, 'notThis').mockResolvedValue({ answer: 'not' });
    renderRun();
    const row = await screen.findByRole('group', { name: 'Follow Acme AI?' });
    await userEvent.click(within(row).getByRole('button', { name: 'Not this one' }));
    expect(not).toHaveBeenCalledWith('r1', 'c1');
  });

  it('links the track once it is watched', async () => {
    vi.spyOn(researchApi, 'page').mockResolvedValue({ ...PAGE, run: { ...PAGE.run, track_id: 'f1' } });
    renderRun();
    expect(await screen.findByRole('link', { name: 'Watching it' })).toHaveAttribute('href', '/read/folder/f1?view=topic');
  });
});

describe('starting research', () => {
  it('starts from the seed typed, or the one the address carries', async () => {
    vi.spyOn(researchApi, 'runs').mockResolvedValue([{ id: 'r0', seed_kind: 'name', seed: 'Widget One', status: 'done', created_at: null }]);
    vi.spyOn(researchApi, 'page').mockResolvedValue(PAGE);
    const start = vi.spyOn(researchApi, 'start').mockResolvedValue({ id: 'r1', seed_kind: 'link' });
    renderRun('/research?seed=https%3A%2F%2Fhub.example%2Facmeai%2Fwidget-1');
    const field = await screen.findByLabelText('What to research');
    expect(field).toHaveValue('https://hub.example/acmeai/widget-1');
    expect(await screen.findByRole('region', { name: 'Earlier research' })).toHaveTextContent('Widget One · a name · done');
    await userEvent.click(screen.getByRole('button', { name: 'Research this' }));
    expect(start).toHaveBeenCalledWith('https://hub.example/acmeai/widget-1');
    expect(await screen.findByRole('heading', { name: /Research: https:\/\/hub.example/ })).toBeInTheDocument();
  });
});
