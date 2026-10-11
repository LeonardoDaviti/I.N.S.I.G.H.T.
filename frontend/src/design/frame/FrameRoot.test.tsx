import { afterEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { frameScenarios, type FrameScenario } from '../fixtures/scenarios';
import { bootFrame, type BootedFrame } from './boot';
import FrameRoot from './FrameRoot';

let booted: BootedFrame | null = null;

afterEach(() => {
  booted?.restore();
  booted = null;
  delete document.documentElement.dataset.frameReady;
  document.documentElement.className = '';
});

function boot(page: string, state: string, theme: 'dark' | 'light' = 'dark') {
  booted = bootFrame(window, { page, state, theme, data: 'fixtures' });
  return booted;
}

/** Let the page's queries and lazy chunks settle after the scenario's steps ran. */
async function settle(frame: BootedFrame) {
  await waitFor(() => expect(document.documentElement.dataset.frameReady).toBeDefined(), { timeout: 5_000 });
  await new Promise((resolve) => setTimeout(resolve, 150));
  return frame.report.events();
}

describe('a frame', () => {
  it('renders the real reader on fixtures, with the top bar, in its own theme', async () => {
    const frame = boot('reader', 'normal', 'light');
    render(<FrameRoot booted={frame} />);

    expect(await screen.findByRole('link', { name: /Prompt caching is now generally available/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'INSIGHT, go to feed' })).toBeInTheDocument();
    expect(document.documentElement).toHaveClass('theme-light');
    expect(window.localStorage.getItem('insight.theme')).toBe('theme-light');
  });

  it('shows a visible bar naming a request the fixtures do not answer', async () => {
    const scenario: FrameScenario = {
      page: 'reader', state: 'gap', label: 'gap', url: '/', documented: false,
      routes: () => [{ path: '/api/config', respond: () => ({ analysis_enabled: false }) }],
    };
    booted = bootFrame(window, { page: 'reader', state: 'gap', theme: 'dark', data: 'fixtures' }, { scenario });
    render(<FrameRoot booted={booted} />);

    const bar = await screen.findByRole('status', { name: 'Frame requests' });
    await waitFor(() => expect(bar).toHaveTextContent(/unmocked request: GET \/api\/feed\?scope=all/));
  });

  it('says so when the URL names a state with no scenario', () => {
    const frame = boot('reader', 'no-such-state');
    render(<FrameRoot booted={frame} />);
    expect(screen.getByText(/no frame scenario for reader\/no-such-state/)).toBeInTheDocument();
  });
});

describe('every frame scenario', () => {
  it.each(frameScenarios().map((scenario) => [`${scenario.page}/${scenario.state}`, scenario] as const))(
    '%s renders inside its fixtures: no unmocked request, its steps done',
    async (_name, scenario) => {
      const frame = boot(scenario.page, scenario.state);
      render(<FrameRoot booted={frame} />);
      const events = await settle(frame);
      expect(document.documentElement.dataset.frameReady).toBe('true');
      expect(events.filter((event) => event.kind === 'unmocked')).toEqual([]);
    },
  );
});
