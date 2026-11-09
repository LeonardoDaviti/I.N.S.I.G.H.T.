import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import MarkXEntityPage from '../../pages/MarkXEntityPage';
import { StoryWindow } from './MarkXOverview';
import type { MarkxEntityPage, MarkxStoryWindow } from '../../services/markx';
import { makeFakeApi as makeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const makeFakeApi = (methods: Record<string, unknown>) => makeApi(methods as Parameters<typeof makeApi>[0]);
const now = new Date().toISOString();

// Issue 0144: a person's own posts ("By"), every story with all its posts and the original first, a Mark IX story
// marked, loose posts by role with mentions collapsed, the old stories to label; the story window on the Worker tab.
const page: MarkxEntityPage = {
  entity: { id: 'e1', name: 'Ivo Kestrel', type: 'person', maker: null, level: 'thing', version: null, variant: null,
    size: null, build: null, status: 'provisional', family: null },
  asked: 'e1', redirected: false, aliases: ['Ivo Kestrel'], maker: null, family: null, versions: [], posts: 6, voices: 3,
  accuracy: { merges: 'm', surges: 's', collisions: 'c' }, queue: [], surges: [], current: true,
  stories: [
    { story: 's1', mark: 'x', headline: 'A weekend tool', voices: 3, newest: now,
      original: { post: 'own1', url: null, why: 'by' },
      posts: [{ id: 'own1', title: 'Weekend hack: a small tool', source: 'Notes', at: now, roles: ['by'] },
              { id: 'p2', title: 'Someone tried the tool', source: 'Channel A', at: now, roles: [], about: false }] },
    { story: 'ix1', mark: 'ix', headline: 'Personal update', voices: 2, newest: now,
      original: { post: null, url: 'https://ivo.example/update', why: 'origin', title: 'The update page', stored: null },
      posts: [{ id: 'p3', title: 'He joins a lab', source: 'Channel B', at: now, roles: ['subject'] }] },
  ],
  loose: [
    { id: 'l1', title: 'He spoke at a conference', source: 'Channel A', at: now, roles: ['subject'] },
    { id: 'l2', title: 'A thread of his', source: 'Notes', at: now, roles: ['by'] },
    { id: 'l3', title: 'Name dropped in passing', source: 'Channel C', at: now, roles: ['mention'] },
  ],
  loose_counts: { report: 1, by: 4, other: 0, mention: 1 },
  by: { sources: [{ id: 'src1', name: 'Notes', kind: 'site', via: 'owner' }], proposed: [{ id: 'src2', name: 'ikestrel', kind: 'x' }], posts: 5 },
  sample: [{ story: 's9', first_at: '2026-05-19T10:00:00Z', answer: null }],
  sources: [{ id: 'src1', name: 'Notes', kind: 'site', posts: 5, reports: 0, by: true }],
};

function open(api: Record<string, unknown> = {}) {
  const calls = { getMarkxEntity: vi.fn().mockResolvedValue(page), answerMarkxEntitySources: vi.fn().mockResolvedValue({}),
    labelMarkxSample: vi.fn().mockResolvedValue({}), ...api };
  renderWithProviders(<Routes><Route path="/markx/entities/:entityId" element={<MarkXEntityPage />} /></Routes>,
    { api: makeFakeApi(calls), route: '/markx/entities/e1' });
  return calls;
}

describe('the person page (issue 0144)', () => {
  it('shows each story with the original first, and marks a Mark IX story', async () => {
    open();
    const x = await screen.findByRole('region', { name: 'A weekend tool' });
    const items = within(x).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Original Weekend hack: a small tool');
    expect(items[0]).toHaveTextContent('its own post');
    expect(items).toHaveLength(2);
    const ix = screen.getByRole('region', { name: 'Personal update' });
    expect(within(ix).getByRole('heading')).toHaveTextContent('Mark IX');
    expect(within(ix).getByRole('link', { name: 'The update page' })).toHaveAttribute('href', 'https://ivo.example/update');
  });

  it('lists his own posts under By, asks about the matching sources, and collapses mentions', async () => {
    const calls = open();
    const by = await screen.findByRole('region', { name: 'By Ivo Kestrel' });
    expect(within(by).getByText('A thread of his')).toBeInTheDocument();
    expect(within(by).getByText(/These sources are Ivo Kestrel: ikestrel\?/)).toBeInTheDocument();
    fireEvent.click(within(by).getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(calls.answerMarkxEntitySources).toHaveBeenCalledWith('e1', ['src2'], 'yes'));
    fireEvent.click(within(by).getByRole('button', { name: 'Show all 4 posts in no story' }));
    await waitFor(() => expect(calls.getMarkxEntity).toHaveBeenCalledWith('e1', 4));
    const about = screen.getByRole('region', { name: 'About Ivo Kestrel' });
    expect(within(about).getByText('He spoke at a conference')).toBeInTheDocument();
    expect(within(about).queryByText('Name dropped in passing')).not.toBeInTheDocument();
    fireEvent.click(within(about).getByRole('button', { name: '1 mention' }));
    expect(within(about).getByText('Name dropped in passing')).toBeInTheDocument();
  });

  it('offers old stories to label', async () => {
    const calls = open();
    const sample = await screen.findByRole('region', { name: 'Old stories to check' });
    fireEvent.click(within(sample).getByRole('button', { name: 'missed a post' }));
    await waitFor(() => expect(calls.labelMarkxSample).toHaveBeenCalledWith('s9', 'missed'));
  });
});

describe('the story window (issue 0144)', () => {
  const state: MarkxStoryWindow = { days: 30, default: 30, in_force: 30, fallback: null, run_days: 30, reached: null,
    precision: { old: { right: 19, wrong: 1, missed: 0, labelled: 20, precision: 0.95 },
                 recent: { right: 9, wrong: 0, missed: 0, labelled: 9, precision: 1 } }, keep: 0.97, min_labels: 20 };

  it('sets the window and shows the old stories’ precision and the fallback', async () => {
    const setMarkxStoryWindow = vi.fn().mockResolvedValue({ story_window_days: null });
    renderWithProviders(<StoryWindow state={{ ...state, days: null, fallback: { days: 120, why: 'stories older than 30 days were right 19 of 20 (95%), under 97%: back to 120 days' } }} />,
      { api: makeFakeApi({ setMarkxStoryWindow }) });
    const section = screen.getByRole('region', { name: 'Story window' });
    expect(within(section).getByText(/Stories older than 30 days: 95% right \(19 of 20\)/)).toBeInTheDocument();
    expect(within(section).getByText(/Back to 120 days: stories older than 30 days were right 19 of 20/)).toBeInTheDocument();
    fireEvent.click(within(section).getByRole('radio', { name: '365 days' }));
    await waitFor(() => expect(setMarkxStoryWindow).toHaveBeenCalledWith(365));
  });
});
