import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import { ThemeProvider } from '../../components/ThemeProvider';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import DesignStudio from '../DesignStudio';

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function renderBench(query = '') {
  return renderWithProviders(
    <ThemeProvider>
      <Routes>
        <Route path="/design/*" element={<><DesignStudio /><Where /></>} />
      </Routes>
    </ThemeProvider>,
    { api: makeFakeApi({}), route: `/design?mode=bench${query}` },
  );
}

const where = () => screen.getByTestId('where').textContent;
const pane = (name: string) => screen.getByRole('figure', { name });
const frameSrc = (name: string) => within(pane(name)).getByTitle(/./).getAttribute('src');
const choose = (group: string, option: string) => within(screen.getByRole('radiogroup', { name: group })).getByRole('radio', { name: option });

afterEach(() => {
  vi.useRealTimers();
});

describe('Bench', () => {
  it('opens on the open prototype: the current page against it, on the same state, width and theme', () => {
    renderBench();
    expect(screen.getByRole('combobox', { name: 'On the bench' })).toHaveValue('2026-10-10-title-wrap');
    expect(frameSrc('current')).toBe('/design/frame/post/long-title?theme=dark&data=fixtures');
    expect(frameSrc('prototype')).toBe('/design/frame/prototype/2026-10-10-title-wrap/long-title?theme=dark&data=fixtures');
  });

  it('moves both panes together when the state, width or theme changes, and keeps it in the URL', async () => {
    const user = userEvent.setup();
    renderBench();
    await user.click(choose('State', 'article'));
    await user.click(choose('Width', '390'));
    await user.click(choose('Theme', 'light'));
    expect(where()).toBe('/design?mode=bench&state=article&width=390&theme=light');
    expect(frameSrc('current')).toBe('/design/frame/post/article?theme=light&data=fixtures');
    expect(frameSrc('prototype')).toBe('/design/frame/prototype/2026-10-10-title-wrap/article?theme=light&data=fixtures');
    expect(within(pane('prototype')).getByTitle(/./).style.width).toBe('390px');
  });

  it('groups the picker: open prototypes first, then pages', () => {
    renderBench();
    const groups = within(screen.getByRole('combobox', { name: 'On the bench' })).getAllByRole('group');
    expect(groups.map((group) => [group.getAttribute('label'), within(group).getAllByRole('option').map((option) => option.textContent)])).toEqual([
      ['open prototypes', ['title-wrap (review)']],
      ['pages', ['Reader', 'Post', 'Sources', 'Shell', 'Blog']],
    ]);
  });

  it('compares two states of a page, each pane with its own state', async () => {
    const user = userEvent.setup();
    renderBench();
    await user.selectOptions(screen.getByRole('combobox', { name: 'On the bench' }), 'reader');
    expect(frameSrc('left')).toBe('/design/frame/reader/normal?theme=dark&data=fixtures');
    expect(frameSrc('right')).toBe('/design/frame/reader/empty?theme=dark&data=fixtures');
    await user.click(choose('Right state', 'loading'));
    expect(where()).toBe('/design?mode=bench&subject=reader&right=loading');
    expect(frameSrc('right')).toBe('/design/frame/reader/loading?theme=dark&data=fixtures');
  });

  it('offers 1400, 390 and the narrowest phone, 320', () => {
    renderBench();
    expect(within(screen.getByRole('radiogroup', { name: 'Width' })).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['1400', '390', '320']);
  });

  it('shows the hypothesis, the principles by title, the status and age, and the doc diff in the drawer', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-11T12:00:00'));
    renderBench();
    const drawer = screen.getByRole('region', { name: 'About this comparison' });
    expect(within(drawer).getByText(/Normal wrap fills the post title's first line/)).toBeInTheDocument();
    expect(within(drawer).getByRole('link', { name: 'P1 Reading first' })).toHaveAttribute('href', '/design');
    expect(within(drawer).getByRole('link', { name: 'P4 Posts in one centred column' })).toBeInTheDocument();
    expect(within(drawer).getByText('review · 1 day')).toBeInTheDocument();
    expect(within(drawer).getByText(/\+- \*\*Title:\*\*.*text-wrap: wrap/)).toBeInTheDocument();
  });

  it('turns accept and reject into the instruction to give the agent, with a copy button', async () => {
    const user = userEvent.setup();
    renderBench();
    const drawer = screen.getByRole('region', { name: 'About this comparison' });
    expect(within(drawer).getByText('accept prototype 2026-10-10-title-wrap')).toBeInTheDocument();
    await user.click(within(drawer).getByRole('button', { name: 'Copy the accept instruction' }));
    expect(await navigator.clipboard.readText()).toBe('accept prototype 2026-10-10-title-wrap');
    expect(within(drawer).getByRole('button', { name: 'Copy the accept instruction' })).toHaveTextContent('Copied');

    const copyReject = within(drawer).getByRole('button', { name: 'Copy the reject instruction' });
    expect(copyReject).toBeDisabled();
    await user.type(within(drawer).getByRole('textbox', { name: 'Why reject it' }), 'pretty reads calmer');
    expect(within(drawer).getByText('reject prototype 2026-10-10-title-wrap: pretty reads calmer')).toBeInTheDocument();
    await user.click(copyReject);
    expect(await navigator.clipboard.readText()).toBe('reject prototype 2026-10-10-title-wrap: pretty reads calmer');
  });

  it('folds the drawer away, and remembers it in the URL', async () => {
    const user = userEvent.setup();
    renderBench();
    await user.click(screen.getByRole('button', { name: 'Notes' }));
    expect(screen.queryByRole('region', { name: 'About this comparison' })).not.toBeInTheDocument();
    expect(where()).toBe('/design?mode=bench&doc=hide');
    expect(screen.getByRole('button', { name: 'Notes' })).toHaveAttribute('aria-expanded', 'false');
  });
});
