import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import { ThemeProvider } from '../ThemeProvider';
import type { Api } from '../../services/api';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import AppShell from './AppShell';
import { activeNavKey, destinations, filterDestinations, NAV_ITEMS, navItems } from './navigation';

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

const FOLDERS = [
  { id: 'a1', name: 'Agentic News', kind: 'track', sort_order: 0 },
  { id: 'b2', name: 'Security', kind: 'track', sort_order: 1 },
];

/** The backend's runtime answer (GET /api/config); `null` = the call fails. */
function shellApi(analysis: boolean | null): Api {
  return makeFakeApi({
    getConfig: analysis === null
      ? vi.fn().mockRejectedValue(new Error('Not Found'))
      : vi.fn().mockResolvedValue({ analysis_enabled: analysis }),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: FOLDERS }),
  });
}

function renderShell(route: string, { analysis = true }: { analysis?: boolean | null } = {}) {
  return renderWithProviders(
    <ThemeProvider>
      <AppShell>
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </AppShell>
    </ThemeProvider>,
    { api: shellApi(analysis), route },
  );
}

async function navWords() {
  const nav = screen.getByRole('navigation', { name: 'Primary' });
  return within(nav).getAllByRole('link').map((link) => link.textContent);
}

describe('navigation model', () => {
  it('the top bar has exactly the five lowercase words, in order, with analysis on', () => {
    expect(navItems(true).map((item) => item.label)).toEqual(['feed', 'tracks', 'briefings', 'sources', 'ingestion', 'blog']);
    expect(NAV_ITEMS).toEqual(navItems(true));
  });

  it('the reading-only top bar is feed / sources / blog', () => {
    expect(navItems(false).map((item) => item.key)).toEqual(['feed', 'sources', 'blog']);
    expect(navItems(false).map((item) => item.to)).toEqual(['/', '/settings/sources', '/blog']);
  });

  it('the reading-only switcher has no briefing, stories, inbox or experts entries', () => {
    const ids = destinations(false).map((d) => d.id);
    for (const d of destinations(false)) {
      expect(d.to).not.toMatch(/^\/(briefing|stories|inbox|experts)/);
      expect(`${d.label} ${d.group}`.toLowerCase()).not.toMatch(/briefing|stor(y|ies)|inbox|expert/);
    }
    expect(ids).toEqual(expect.arrayContaining(['feed-unread', 'sources', 'sources-health', 'ingestion']));
  });

  it('the reading-only switcher has one entry per track, and no tracks list', () => {
    const items = destinations(false, [
      { id: 'a1', name: 'Agentic News' },
      { id: 'b 2', name: 'مراجعة' },
    ]);
    expect(items.find((d) => d.to === '/tracks')).toBeUndefined();
    const tracks = items.filter((d) => d.group === 'tracks');
    expect(tracks.map((d) => [d.label, d.to])).toEqual([
      ['Agentic News', '/tracks/a1'],
      ['مراجعة', '/tracks/b%202'],
    ]);
    expect(filterDestinations('agentic', items).map((d) => d.to)).toEqual(['/tracks/a1']);
    expect(filterDestinations('track', items).map((d) => d.to)).toEqual(['/tracks/a1', '/tracks/b%202']);
  });

  it('with analysis on the switcher is unchanged', () => {
    expect(destinations(true, [{ id: 'a1', name: 'Agentic News' }]).map((d) => d.id)).toEqual([
      'feed-unread', 'feed-starred', 'feed-all', 'feed-by-source', 'tracks', 'briefing', 'briefing-topics',
      'briefing-vertical', 'stories', 'inbox', 'sources', 'sources-health', 'ingestion', 'blog',
    ]);
  });

  it('reading-only, Ingestion in the switcher opens the ingestion tab under sources', () => {
    const ingestion = destinations(false).find((d) => d.id === 'ingestion');
    expect(ingestion?.to).toBe('/settings/sources?tab=ingestion');
    expect(ingestion?.group).toBe('sources');
    expect(destinations(true).find((d) => d.id === 'ingestion')?.to).toBe('/ingestion');
  });

  it('the ingestion tab under sources is the sources word', () => {
    expect(activeNavKey('/settings/sources?tab=ingestion')).toBe('sources');
  });

  it('reading-only: a track page belongs to the feed (tracks live in the reader rail)', () => {
    expect(activeNavKey('/tracks/abc', false)).toBe('feed');
    expect(activeNavKey('/tracks/abc', true)).toBe('tracks');
  });

  it.each([
    ['/', 'feed'],
    ['/read/folder/abc', 'feed'],
    ['/posts/42', 'feed'],
    ['/tracks', 'tracks'],
    ['/tracks/abc', 'tracks'],
    ['/experts', 'tracks'],
    ['/briefing/vertical/source/x', 'briefings'],
    ['/stories', 'briefings'],
    ['/inbox', 'briefings'],
    ['/settings/sources', 'sources'],
    ['/ingestion/jobs', 'ingestion'],
    ['/blog', 'blog'],
    ['/blog/junior-to-senior', 'blog'],
    ['/nowhere', null],
    ['/briefingx', null],
  ])('%s → %s', (path, key) => {
    expect(activeNavKey(path)).toBe(key);
  });

  it('the switcher filter matches label, group and keywords, every word', () => {
    expect(filterDestinations('health').map((d) => d.id)).toEqual(['sources-health']);
    expect(filterDestinations('BRIEF vert').map((d) => d.id)).toEqual(['briefing-vertical']);
    expect(filterDestinations('zzz')).toEqual([]);
    expect(filterDestinations('').length).toBeGreaterThan(5);
  });
});

describe('AppShell', () => {
  it('shows the wordmark and marks the current nav word with aria-current', () => {
    renderShell('/settings/sources?tab=health');
    expect(screen.getByRole('link', { name: 'INSIGHT, go to feed' })).toHaveAttribute('href', '/');
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    const current = nav.querySelectorAll('[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent('sources');
  });

  it('the feed word is current on the reader home', async () => {
    renderShell('/');
    expect(screen.getByRole('link', { name: 'feed' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByRole('link', { name: 'tracks' })).not.toHaveAttribute('aria-current');
  });

  it('the backend says analysis is on: the five words', async () => {
    renderShell('/');
    await screen.findByRole('link', { name: 'briefings' });
    expect(await navWords()).toEqual(['feed', 'tracks', 'briefings', 'sources', 'ingestion', 'blog']);
  });

  it('the backend says analysis is off: feed / sources / blog', async () => {
    renderShell('/', { analysis: false });
    await screen.findByRole('link', { name: 'sources' });
    expect(await navWords()).toEqual(['feed', 'sources', 'blog']);
  });

  it('when /api/config fails, the build flag decides (off in tests)', async () => {
    const { queryClient } = renderShell('/', { analysis: null });
    await vi.waitFor(() => expect(queryClient.getQueryState(['config'])?.status).toBe('error'));
    expect(await navWords()).toEqual(['feed', 'sources', 'blog']);
  });

  it('reading-only ⌘K: one entry per track, no briefings', async () => {
    const user = userEvent.setup();
    renderShell('/', { analysis: false });
    await screen.findByRole('link', { name: 'sources' });
    await user.keyboard('{Control>}k{/Control}');
    await screen.findByRole('option', { name: /Agentic News/ });
    const labels = screen.getAllByRole('option').map((option) => option.textContent);
    expect(labels.join(' ')).not.toMatch(/briefing|Stories|inbox/i);
    await user.type(screen.getByRole('combobox'), 'security');
    await user.keyboard('{Enter}');
    expect(screen.getByTestId('where')).toHaveTextContent('/tracks/b2');
  });

  it('Ctrl+K opens the quick switcher; typing filters; Enter navigates', async () => {
    const user = userEvent.setup();
    renderShell('/');
    expect(screen.queryByRole('dialog')).toBeNull();
    await user.keyboard('{Control>}k{/Control}');
    const input = await screen.findByRole('combobox', { name: 'Go to' });
    await user.type(input, 'health');
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{Enter}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByTestId('where')).toHaveTextContent('/settings/sources?tab=health');
  });

  it('arrow keys move the active option, and the switcher can toggle the theme', async () => {
    const user = userEvent.setup();
    renderShell('/');
    await user.click(screen.getByRole('button', { name: 'Open quick switcher' }));
    const input = await screen.findByRole('combobox');
    await user.type(input, 'theme');
    expect(screen.getByRole('option', { name: /switch to light theme/i })).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{Enter}');
    expect(document.documentElement).toHaveClass('theme-light');
  });

  it('shows an empty message when nothing matches', async () => {
    const user = userEvent.setup();
    renderShell('/');
    await user.keyboard('{Control>}k{/Control}');
    await user.type(await screen.findByRole('combobox'), 'qwerty');
    expect(screen.getByText(/No page matches/)).toBeInTheDocument();
  });
});
