import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';

import { frameScenarios, type FrameScenario } from '../fixtures/scenarios';
import { bootFrame, type BootedFrame } from './boot';
import FrameRoot from './FrameRoot';
import { WALK, WALK_MESSAGE } from '../wall/walk';

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

describe('a walk frame', () => {
  // jsdom has no layout: ⌘K scrolls its active option into view.
  beforeAll(() => { Element.prototype.scrollIntoView ??= () => {}; });

  /** What the frame posts to the studio (its parent; in jsdom, itself). */
  function inbox() {
    const messages: { type: string; step?: number; ok?: boolean; error?: string; path?: string }[] = [];
    const listen = (event: MessageEvent) => { if (typeof event.data?.type === 'string') messages.push(event.data); };
    window.addEventListener('message', listen);
    return { messages, stop: () => window.removeEventListener('message', listen) };
  }

  const send = (step: number) => window.dispatchEvent(new MessageEvent('message', {
    data: { type: WALK_MESSAGE.run, step }, origin: window.location.origin, source: window,
  }));

  it('walks the real pages on fixtures: post, back, source, its sheet, closed, a track by ⌘K, the feed', async () => {
    const { messages, stop } = inbox();
    const frame = boot('reader', 'normal');
    render(<FrameRoot booted={frame} walk />);
    await waitFor(() => expect(messages.some((message) => message.type === WALK_MESSAGE.ready)).toBe(true));

    const seen: Record<string, () => void> = {
      'open-post': () => expect(screen.getByRole('button', { name: /^Back/ })).toBeInTheDocument(),
      'source-name': () => expect(within(screen.getByRole('dialog')).getAllByText(/Simon Willison/).length).toBeGreaterThan(0),
      'close-sheet': () => expect(screen.queryByRole('dialog')).toBeNull(),
      track: () => expect(screen.getAllByText('AI engineering').length).toBeGreaterThan(0),
      home: () => expect(screen.getByRole('link', { name: /Prompt caching/ })).toBeInTheDocument(),
    };
    for (const [index, step] of WALK.entries()) {
      send(index);
      await waitFor(() => expect(messages.find((message) => message.type === WALK_MESSAGE.done && message.step === index)).toBeDefined(), { timeout: 8_000 });
      const done = messages.find((message) => message.type === WALK_MESSAGE.done && message.step === index)!;
      expect(done, `${step.id}: ${done.error}`).toMatchObject({ ok: true });
      seen[step.id]?.();
      if (index === 1) expect(done.path).toMatch(/^\/posts\//);
    }
    stop();
  }, 30_000);

  it('ignores walk messages unless it is a walk frame', async () => {
    const { messages, stop } = inbox();
    const frame = boot('reader', 'normal');
    render(<FrameRoot booted={frame} />);
    await settle(frame);
    send(1);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(messages.filter((message) => message.type !== WALK_MESSAGE.run)).toEqual([]);
    stop();
  });
});
