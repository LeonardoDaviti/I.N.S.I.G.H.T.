import { describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation, useNavigate } from 'react-router-dom';

import SourcesConfig from './SourcesConfig';
import { healthResponse, healthRow } from '../components/ops/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { SourceAnatomyRow, SourceGives } from '../services/api';

const gives = (over: Partial<SourceGives> = {}): SourceGives => ({ posts: 0, read: 0, stories: 0, first: 0, classics: 0, links: 0, ...over });

function anatomyRow(id: string, over: Partial<SourceAnatomyRow> = {}): SourceAnatomyRow {
  return {
    source_id: id, display_name: id, address: `https://${id}.example/feed`, platform: 'rss', enabled: true,
    kind: 'feed', full_text: 'feed', watch_changes: null, watched_pages: 0, validators: true,
    status: 'deferred', interval_hours: 6, interval_basis: 'tier', next_due_at: new Date(Date.now() + 2 * 3_600_000).toISOString(),
    last_attempt_at: new Date(Date.now() - 3 * 3_600_000).toISOString(), last_outcome: 'healthy', last_error: null, last_error_at: null,
    recent: gives(), all: gives(), ...over,
  };
}

const ROWS = [
  anatomyRow('Few Posts', { recent: gives({ posts: 3, stories: 9 }), all: gives({ posts: 300, stories: 20 }) }),
  anatomyRow('simon', {
    display_name: 'Simon Willison’s Weblog', full_text: 'on', recent: gives({ posts: 40, read: 4, stories: 2, first: 1, classics: 1, links: 80 }),
    all: gives({ posts: 900, read: 31, stories: 15, first: 6, classics: 7, links: 2100 }),
  }),
  anatomyRow('tg', {
    display_name: null, address: 'https://tg.i-c-a.su/rss/dennis_it?limit=50', kind: 'telegram', validators: null,
    last_outcome: 'error', last_error: 'HTTP 404', recent: gives({ posts: 12 }), all: gives({ posts: 12 }),
  }),
];

let browserBack: () => void = () => {};
function Where() {
  const location = useLocation();
  const navigate = useNavigate();
  browserBack = () => navigate(-1);
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}
const where = () => screen.getByTestId('where').textContent;

function setup(route = '/settings/sources?tab=ingestion&sub=sources', overrides: Record<string, unknown> = {}) {
  const methods = {
    getSourceAnatomy: vi.fn().mockResolvedValue({ success: true, window_days: 30, generated_at: new Date().toISOString(), rows: ROWS }),
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([healthRow({ source_id: 'simon', display_name: 'Simon Willison’s Weblog' })])),
    getSources: vi.fn().mockResolvedValue({ success: true, sources: [], total: 0 }),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
    getSourceFolders: vi.fn().mockResolvedValue({ success: true, folder_ids: [] }),
    getOperationsOverview: vi.fn().mockResolvedValue({ success: true, jobs: [], alerts: [] }),
    getSchedulerConfig: vi.fn().mockResolvedValue({ success: true, scheduler: { interval_hours: 24, ingest_tick_minutes: 60, state: {} } }),
    getVersion: vi.fn().mockResolvedValue({ version: null, commit: null, commit_date: null }),
    ...overrides,
  };
  renderWithProviders(<><SourcesConfig /><Where /></>, { api: makeFakeApi(methods), route });
  return methods;
}

const names = () => screen.getAllByRole('row').slice(2).map((row) => within(row).getAllByRole('cell')[0].textContent);

describe('Sources → ingestion → sources (issue 0054)', () => {
  it('is a view of the ingestion tab, next to the overview', async () => {
    setup();
    const nav = await screen.findByRole('navigation', { name: 'Ingestion views' });
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['overview', 'sources', 'archive', 'jobs', 'logs']);
    expect(within(nav).getByRole('link', { name: 'sources' })).toHaveAttribute('aria-current', 'page');
  });

  it('shows how each source is read and what it gave, the most posts first, all time on hover', async () => {
    setup();
    await screen.findByRole('table');
    expect(names()).toEqual(['Simon Willison’s Weblog', '@dennis_it (no name of its own)', 'Few Posts']);
    const simon = screen.getAllByRole('row')[2];
    const cells = within(simon).getAllByRole('cell').map((cell) => cell.textContent);
    expect(cells).toEqual(['Simon Willison’s Weblog', 'Feed', 'on', '—', 'yes', '6h', '3h', '40', '4', '2', '1', '1', '80']);
    expect(within(simon).getByText('80')).toHaveAttribute('title', 'All time: 2,100');
    const tg = screen.getAllByRole('row')[3];
    expect(within(tg).getByText('failed 3h: HTTP 404')).toBeInTheDocument();
    expect(within(tg).getByText('Telegram')).toBeInTheDocument();
  });

  it('every column header sorts; pressing it again reverses', async () => {
    setup();
    await screen.findByRole('table');
    await userEvent.click(screen.getByRole('button', { name: 'Sort by Stories' }));
    expect(names()[0]).toBe('Few Posts');
    expect(screen.getByRole('button', { name: 'Sort by Stories, descending' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Sort by Stories, descending' }));
    expect(names()[0]).toBe('@dennis_it (no name of its own)');
    await userEvent.click(screen.getByRole('button', { name: 'Sort by Source' }));
    expect(names()).toEqual(['@dennis_it (no name of its own)', 'Few Posts', 'Simon Willison’s Weblog']);
    expect(screen.getByRole('button', { name: 'Sort by Source, ascending' }).closest('th')).toHaveAttribute('aria-sort', 'ascending');
  });

  it('a row opens the source’s sheet; Back closes it and stays on the view', async () => {
    setup();
    await screen.findByRole('table');
    await userEvent.click(screen.getByRole('button', { name: 'Simon Willison’s Weblog' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByRole('heading', { name: 'Simon Willison’s Weblog' })).toBeInTheDocument();
    expect(where()).toBe('/settings/sources?tab=ingestion&sub=sources&source=simon');
    act(() => browserBack());
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(where()).toBe('/settings/sources?tab=ingestion&sub=sources');
  });

  it('a click anywhere on the row opens it too', async () => {
    setup();
    await screen.findByRole('table');
    await userEvent.click(within(screen.getAllByRole('row')[2]).getByText('80'));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('says so when it cannot load', async () => {
    setup(undefined, { getSourceAnatomy: vi.fn().mockRejectedValue(new Error('boom')) });
    expect(await screen.findByText('Could not load the sources')).toBeInTheDocument();
  });
});
