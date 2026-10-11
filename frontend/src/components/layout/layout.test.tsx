import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import { ThemeProvider } from '../ThemeProvider';
import type { Api } from '../../services/api';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import AppShell from './AppShell';
import { activeNavKey, destinations, filterDestinations, insideDesignFrame, NAV_ITEMS } from './navigation';

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

const FOLDERS = [
  { id: 'a1', name: 'Agentic News', kind: 'track', sort_order: 0 },
  { id: 'b2', name: 'Security', kind: 'track', sort_order: 1 },
];

function shellApi(): Api {
  return makeFakeApi({
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: FOLDERS }),
  });
}

function renderShell(route: string) {
  return renderWithProviders(
    <ThemeProvider>
      <AppShell>
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </AppShell>
    </ThemeProvider>,
    { api: shellApi(), route },
  );
}

async function navWords() {
  const nav = screen.getByRole('navigation', { name: 'Primary' });
  return within(nav).getAllByRole('link').map((link) => link.textContent);
}

describe('navigation model', () => {
  it('the top bar is feed / sources / blog', () => {
    expect(NAV_ITEMS.map((item) => item.key)).toEqual(['feed', 'sources', 'blog']);
    expect(NAV_ITEMS.map((item) => item.to)).toEqual(['/', '/settings/sources', '/blog']);
  });

  it('the switcher has no briefing, stories, inbox or experts entries', () => {
    const ids = destinations().map((d) => d.id);
    for (const d of destinations()) {
      expect(d.to).not.toMatch(/^\/(briefing|stories|inbox|experts)/);
      expect(`${d.label} ${d.group}`.toLowerCase()).not.toMatch(/briefing|stor(y|ies)|inbox|expert/);
    }
    expect(ids).toEqual(expect.arrayContaining(['feed-unread', 'sources', 'sources-health', 'ingestion']));
  });

  it('the switcher has one entry per track, and no tracks list', () => {
    const items = destinations([
      { id: 'a1', name: 'Agentic News' },
      { id: 'b 2', name: 'مراجعة' },
    ]);
    expect(items.find((d) => d.to === '/tracks')).toBeUndefined();
    const tracks = items.filter((d) => d.group === 'tracks');
    expect(tracks.map((d) => [d.label, d.to])).toEqual([
      ['Agentic News', '/read/folder/a1'],
      ['مراجعة', '/read/folder/b%202'],
    ]);
    expect(filterDestinations('agentic', items).map((d) => d.to)).toEqual(['/read/folder/a1']);
    expect(filterDestinations('track', items).map((d) => d.to)).toEqual(['/read/folder/a1', '/read/folder/b%202']);
  });

  it('⌘K reaches the design studio; the top bar never shows it', () => {
    const items = destinations([{ id: 'a1', name: 'Agentic News' }]);
    expect(items.at(-1)).toMatchObject({ id: 'design-studio', label: 'Design studio', to: '/design' });
    expect(NAV_ITEMS.map((item) => item.to)).not.toContain('/design');
    expect(filterDestinations('principles tokens', destinations()).map((d) => d.id)).toEqual(['design-studio']);
  });

  it('inside a design studio frame, ⌘K leaves the design studio out', () => {
    expect(destinations([], { studio: false }).map((d) => d.id)).not.toContain('design-studio');
    window.history.pushState({}, '', '/design/frame/reader/normal?theme=dark');
    expect(insideDesignFrame()).toBe(true);
    window.history.pushState({}, '', '/');
    expect(insideDesignFrame()).toBe(false);
  });

  it('Ingestion in the switcher opens the ingestion tab under sources', () => {
    const ingestion = destinations().find((d) => d.id === 'ingestion');
    expect(ingestion?.to).toBe('/settings/sources?tab=ingestion');
    expect(ingestion?.group).toBe('sources');
  });

  it('the ingestion tab under sources is the sources word', () => {
    expect(activeNavKey('/settings/sources?tab=ingestion')).toBe('sources');
  });

  it.each([
    ['/', 'feed'],
    ['/read/folder/abc', 'feed'],
    ['/posts/42', 'feed'],
    ['/tracks/abc', 'feed'],
    ['/settings/sources', 'sources'],
    ['/blog', 'blog'],
    ['/blog/junior-to-senior', 'blog'],
    ['/nowhere', null],
  ])('%s → %s', (path, key) => {
    expect(activeNavKey(path)).toBe(key);
  });

  it('the switcher filter matches label, group and keywords, every word', () => {
    expect(filterDestinations('health').map((d) => d.id)).toEqual(['sources-health']);
    expect(filterDestinations('starred feed').map((d) => d.id)).toEqual(['feed-starred']);
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
    expect(screen.getByRole('link', { name: 'sources' })).not.toHaveAttribute('aria-current');
  });

  it('the top bar shows feed / sources / blog', async () => {
    renderShell('/');
    expect(await navWords()).toEqual(['feed', 'sources', 'blog']);
  });

  it('⌘K: one entry per track, no briefings', async () => {
    const user = userEvent.setup();
    renderShell('/');
    await user.keyboard('{Control>}k{/Control}');
    await screen.findByRole('option', { name: /Agentic News/ });
    const labels = screen.getAllByRole('option').map((option) => option.textContent);
    expect(labels.join(' ')).not.toMatch(/briefing|Stories|inbox/i);
    await user.type(screen.getByRole('combobox'), 'security');
    await user.keyboard('{Enter}');
    expect(screen.getByTestId('where')).toHaveTextContent('/read/folder/b2');
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

  it('⌘K opens the design studio', async () => {
    const user = userEvent.setup();
    renderShell('/');
    await user.keyboard('{Control>}k{/Control}');
    await user.type(await screen.findByRole('combobox'), 'design');
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([expect.stringMatching(/^Design studio/)]);
    await user.keyboard('{Enter}');
    expect(screen.getByTestId('where')).toHaveTextContent('/design');
  });

  it('shows an empty message when nothing matches', async () => {
    const user = userEvent.setup();
    renderShell('/');
    await user.keyboard('{Control>}k{/Control}');
    await user.type(await screen.findByRole('combobox'), 'qwerty');
    expect(screen.getByText(/No page matches/)).toBeInTheDocument();
  });
});
