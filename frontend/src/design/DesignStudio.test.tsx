import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import { ThemeProvider } from '../components/ThemeProvider';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import DesignStudio from './DesignStudio';

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

/** The studio at a URL, as App.tsx mounts it; the studio never calls the API. */
function renderStudio(route: string) {
  return renderWithProviders(
    <ThemeProvider>
      <Routes>
        <Route path="/design/*" element={<><DesignStudio /><Where /></>} />
      </Routes>
    </ThemeProvider>,
    { api: makeFakeApi({}), route },
  );
}

const where = () => screen.getByTestId('where').textContent;
const mode = () => screen.getByRole('radiogroup', { name: 'Studio mode' });

describe('the studio shell', () => {
  it('opens on the principles in Handbook mode, without the doc\'s meta block', () => {
    renderStudio('/design');
    expect(within(mode()).getByRole('radio', { name: 'handbook' })).toBeChecked();
    expect(screen.getByRole('heading', { level: 1, name: 'Principles' })).toBeInTheDocument();
    expect(screen.getByText(/Reading first\./)).toBeInTheDocument();
    expect(screen.queryByText(/kind: principles/)).not.toBeInTheDocument();
  });

  it('switches mode from the segmented control and keeps it in ?mode=', async () => {
    const user = userEvent.setup();
    renderStudio('/design');
    await user.click(within(mode()).getByRole('radio', { name: 'wall' }));
    expect(where()).toBe('/design?mode=wall');
    expect(within(mode()).getByRole('radio', { name: 'wall' })).toBeChecked();
    expect(screen.getByRole('region', { name: 'Wall' })).toBeInTheDocument();
    await user.click(within(mode()).getByRole('radio', { name: 'handbook' }));
    expect(where()).toBe('/design');
  });

  it('→ and ← step through the modes, wrapping, unless a field has focus', async () => {
    const user = userEvent.setup();
    renderStudio('/design/system?mode=bench');
    expect(screen.getByRole('region', { name: 'Bench' })).toBeInTheDocument();
    await user.keyboard('{ArrowRight}');
    expect(where()).toBe('/design/system');
    await user.keyboard('{ArrowLeft}');
    expect(where()).toBe('/design/system?mode=bench');
    await user.keyboard('{ArrowLeft}');
    expect(where()).toBe('/design/system?mode=wall');
    const field = document.createElement('input');
    document.body.append(field);
    field.focus();
    await user.keyboard('{ArrowRight}');
    expect(where()).toBe('/design/system?mode=wall');
    field.remove();
  });
});

describe('the Handbook', () => {
  const rail = () => screen.getByRole('navigation', { name: 'Design studio' });

  it('reaches every page doc from the rail, which marks the current one', async () => {
    const user = userEvent.setup();
    renderStudio('/design');
    await user.click(within(rail()).getByRole('link', { name: 'Post' }));
    expect(where()).toBe('/design/pages/post');
    expect(screen.getByRole('heading', { level: 1, name: 'Post' })).toBeInTheDocument();
    expect(within(rail()).getByRole('link', { name: 'Post' })).toHaveAttribute('aria-current', 'page');
  });

  it('puts a specimen slot under a page doc, driven by the doc\'s states, a width and a theme', async () => {
    const user = userEvent.setup();
    renderStudio('/design/pages/reader');
    const states = screen.getByRole('radiogroup', { name: 'State' });
    expect(within(states).getAllByRole('radio').map((radio) => radio.textContent)).toEqual([
      'normal', 'empty', 'empty-scope', 'loading', 'error', 'worst',
    ]);
    expect(screen.getByRole('figure', { name: 'reader · normal · 1400 · dark' })).toBeInTheDocument();
    await user.click(within(states).getByRole('radio', { name: 'loading' }));
    await user.click(within(screen.getByRole('radiogroup', { name: 'Width' })).getByRole('radio', { name: '390' }));
    await user.click(within(screen.getByRole('radiogroup', { name: 'Theme' })).getByRole('radio', { name: 'light' }));
    expect(where()).toBe('/design/pages/reader?state=loading&width=390&theme=light');
    expect(screen.getByRole('figure', { name: 'reader · loading · 390 · light' })).toBeInTheDocument();
  });

  it('gives a parked doc its slot at the normal state', () => {
    renderStudio('/design/parked/inbox');
    expect(screen.getByRole('heading', { level: 1, name: 'Analyst inbox' })).toBeInTheDocument();
    expect(screen.getByRole('figure', { name: 'inbox · normal · 1400 · dark' })).toBeInTheDocument();
  });

  it('renders the decisions log', () => {
    renderStudio('/design/decisions');
    expect(screen.getByRole('heading', { level: 1, name: 'Decisions' })).toBeInTheDocument();
    expect(screen.getByText(/Mark IX is monochrome/)).toBeInTheDocument();
  });

  it('sends /design/principles to the home', () => {
    renderStudio('/design/principles');
    expect(where()).toBe('/design');
  });

  it('says so when nothing lives at an address', () => {
    renderStudio('/design/pages/nowhere');
    expect(screen.getByRole('heading', { name: 'Not in the studio' })).toBeInTheDocument();
  });
});
