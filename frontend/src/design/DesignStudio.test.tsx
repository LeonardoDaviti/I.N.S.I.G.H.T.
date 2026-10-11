import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, screen, within } from '@testing-library/react';
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

  it('lists no open prototype yet, and names an unknown one', () => {
    renderStudio('/design/prototypes/2026-01-01-nothing');
    expect(within(rail()).getByText('none open')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Not in the studio' })).toBeInTheDocument();
    expect(screen.getByText(/No prototype lives at this address/)).toBeInTheDocument();
  });

  it('says so when nothing lives at an address', () => {
    renderStudio('/design/pages/nowhere');
    expect(screen.getByRole('heading', { name: 'Not in the studio' })).toBeInTheDocument();
  });
});

describe('the System section', () => {
  let style: HTMLStyleElement | undefined;
  const realAnimate = HTMLElement.prototype.animate;
  afterEach(() => {
    HTMLElement.prototype.animate = realAnimate;
    style?.remove();
    document.documentElement.className = '';
    vi.unstubAllGlobals();
  });

  /** A slice of index.css: the studio reads whatever the page defines. */
  function defineTokens() {
    style = document.createElement('style');
    style.textContent = [
      ':root, :root.theme-dark { --bg: 18 18 18; --text: 242 242 242; --scrim: 0 0 0 / 0.6 }',
      ':root.theme-light { --bg: 255 255 255; --text: 17 17 17 }',
      ':root { --ease-out: cubic-bezier(0.23, 1, 0.32, 1); --dur-press: 120ms; --dur-sheet: 260ms }',
    ].join('\n');
    document.head.append(style);
  }

  const tokenRow = (name: string) => screen.getByRole('row', { name: new RegExp(`^${name} `) });

  it('reads each documented token live from the page, and follows the theme', async () => {
    defineTokens();
    renderStudio('/design/system');
    expect(screen.getByRole('heading', { level: 1, name: 'System' })).toBeInTheDocument();
    expect(tokenRow('--bg')).toHaveTextContent('#121212');
    expect(tokenRow('--scrim')).toHaveTextContent(/0 0 0 ?\/ ?0\.6/);
    // Documented in tokens.md, not defined by this page: said out loud.
    expect(tokenRow('--surface')).toHaveTextContent('not defined');
    await act(async () => document.documentElement.classList.add('theme-light'));
    expect(tokenRow('--bg')).toHaveTextContent('#ffffff');
  });

  it('lists the motion durations live, and replays them unless motion is reduced', async () => {
    defineTokens();
    const user = userEvent.setup();
    renderStudio('/design/system');
    const motion = screen.getByRole('region', { name: 'Motion' });
    expect(within(motion).getByText('--dur-press')).toBeInTheDocument();
    expect(within(motion).getByText('260ms')).toBeInTheDocument();
    // jsdom drops the spaces a browser keeps.
    expect(within(motion).getByText(/cubic-bezier\(0.23, ?1, ?0.32, ?1\)/)).toBeInTheDocument();
    const animate = vi.fn();
    HTMLElement.prototype.animate = animate;
    await user.click(within(motion).getByRole('button', { name: 'Replay' }));
    expect(animate).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ duration: 260, easing: expect.stringMatching(/cubic-bezier\(0.23, ?1, ?0.32, ?1\)/) }));
  });

  it('under reduced motion, the replay only fades', async () => {
    defineTokens();
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), addEventListener() {}, removeEventListener() {} }));
    const user = userEvent.setup();
    renderStudio('/design/system');
    const motion = screen.getByRole('region', { name: 'Motion' });
    expect(within(motion).getByText(/Reduced motion is on/)).toBeInTheDocument();
    const animate = vi.fn();
    HTMLElement.prototype.animate = animate;
    await user.click(within(motion).getByRole('button', { name: 'Replay' }));
    for (const [keyframes, options] of animate.mock.calls) {
      expect(keyframes).toEqual([{ opacity: 0 }, { opacity: 1 }]);
      expect(options).toMatchObject({ duration: 150 });
    }
    expect(animate).toHaveBeenCalled();
  });

  it('shows the type scale, the radii and every status as glyph plus word', () => {
    renderStudio('/design/system');
    for (const step of ['display', 'title', 'heading', 'body', 'reading', 'small', 'micro']) {
      expect(within(screen.getByRole('region', { name: 'Type scale' })).getByText(step)).toBeInTheDocument();
    }
    expect(within(screen.getByRole('region', { name: 'Space and radii' })).getByText('rounded-md')).toBeInTheDocument();
    const status = screen.getByRole('region', { name: 'Status' });
    for (const word of ['ok', 'due', 'scheduled', 'backoff', 'failing', 'unavailable', 'disabled', 'running', 'unread', 'read', 'starred']) {
      expect(within(status).getAllByText(word).length).toBeGreaterThan(0);
    }
  });

  it('opens a system doc with its live specimen under it', () => {
    defineTokens();
    renderStudio('/design/system/motion');
    expect(screen.getByRole('heading', { level: 1, name: 'Motion' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Motion' })).toBeInTheDocument();
  });
});

describe('the Components section', () => {
  it('lists every primitive under the inventory doc', () => {
    renderStudio('/design/components');
    expect(screen.getByRole('heading', { level: 1, name: 'Component inventory' })).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Primitives' });
    expect(within(list).getByRole('link', { name: 'StatusGlyph' })).toHaveAttribute('href', '/design/components/StatusGlyph');
    expect(within(list).getAllByRole('link').length).toBeGreaterThan(10);
  });

  it('shows a primitive\'s variants and states, with its source and its rule from the inventory', () => {
    renderStudio('/design/components/Button');
    expect(screen.getByRole('heading', { level: 1, name: 'Button' })).toBeInTheDocument();
    expect(screen.getByText('src/components/ui/Button.tsx')).toBeInTheDocument();
    expect(screen.getByText(/one primary per view/)).toBeInTheDocument();
    const specimen = screen.getByRole('region', { name: 'Specimen' });
    for (const name of ['Primary', 'Secondary', 'Ghost', 'Delete source']) {
      expect(within(specimen).getAllByRole('button', { name }).length).toBeGreaterThan(0);
    }
    expect(within(specimen).getAllByRole('button', { name: 'Secondary' }).some((button) => button.hasAttribute('disabled'))).toBe(true);
  });

  it('renders every specimen without throwing', async () => {
    const { COMPONENT_SPECIMENS } = await import('./library');
    for (const name of COMPONENT_SPECIMENS.keys()) {
      const { unmount } = renderStudio(`/design/components/${name}`);
      expect(screen.getByRole('heading', { level: 1, name })).toBeInTheDocument();
      unmount();
    }
  });

  it('says so for a primitive that does not exist', () => {
    renderStudio('/design/components/Nope');
    expect(screen.getByRole('heading', { name: 'Not in the studio' })).toBeInTheDocument();
  });
});
