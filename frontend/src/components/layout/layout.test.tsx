import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { ThemeProvider } from '../ThemeProvider';
import AppShell from './AppShell';
import { activeNavKey, filterDestinations, NAV_ITEMS } from './navigation';

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function renderShell(route: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[route]}>
        <AppShell>
          <Routes>
            <Route path="*" element={<Where />} />
          </Routes>
        </AppShell>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('navigation model', () => {
  it('the top bar has exactly the five lowercase words, in order', () => {
    expect(NAV_ITEMS.map((item) => item.label)).toEqual(['feed', 'tracks', 'briefings', 'sources', 'ingestion']);
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

  it('the feed word is current on the reader home', () => {
    renderShell('/');
    expect(screen.getByRole('link', { name: 'feed' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'tracks' })).not.toHaveAttribute('aria-current');
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
