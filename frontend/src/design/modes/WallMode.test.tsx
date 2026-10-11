import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';

import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { SITE_NODES } from '../wall/siteMap';
import { WALK, WALK_MESSAGE } from '../wall/walk';
import WallMode from './WallMode';

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.search}</p>;
}

function renderWall(search = '?mode=wall') {
  return renderWithProviders(
    <Routes>
      <Route path="/design/*" element={<><WallMode /><Where /></>} />
    </Routes>,
    { api: makeFakeApi({}), route: `/design${search}` },
  );
}

const where = () => screen.getByTestId('where').textContent;
const page = (name: string) => screen.getByRole('figure', { name });
const pageFrames = () => [...screen.getByRole('region', { name: 'Site map' }).querySelectorAll('iframe')];

afterEach(() => vi.restoreAllMocks());

describe('the Wall', () => {
  it('shows every page in use as a live frame with its name, route and the principles it cites', () => {
    renderWall();
    for (const node of SITE_NODES) {
      const figure = page(node.name);
      expect(within(figure).getByText(node.route)).toBeInTheDocument();
      expect(within(figure).getByText(node.principles.map((n) => `P${n}`).join(' '))).toBeInTheDocument();
    }
    const post = within(page('Post')).getByTitle(/^post · article/);
    expect(post).toHaveAttribute('src', '/design/frame/post/article?theme=dark&data=fixtures');
    expect(pageFrames()).toHaveLength(SITE_NODES.length);
  });

  it('labels the moves between pages by what you do', () => {
    renderWall();
    const map = screen.getByRole('region', { name: 'Site map' });
    expect(within(map).getByText('click a title')).toBeInTheDocument();
    expect(within(map).getAllByText('source name')).toHaveLength(2);
  });

  it('a principle chip lights the pages that cite it and dims the rest; a click keeps it', async () => {
    const user = userEvent.setup();
    renderWall();
    const chip = screen.getByRole('button', { name: /^P4 Posts in one centred column/ });
    await user.hover(chip);
    expect(page('Post')).toHaveAttribute('data-lit', 'true');
    expect(page('Sources')).toHaveAttribute('data-lit', 'false');
    await user.unhover(chip);
    expect(page('Sources')).not.toHaveAttribute('data-lit');
    await user.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    expect(where()).toBe('?mode=wall&p=4');
    expect(page('Sources')).toHaveAttribute('data-lit', 'false');
    expect(screen.getByText(/A post reads in one centred measure/)).toBeInTheDocument();
    expect(screen.getByText('· 1 of 11 pages')).toBeInTheDocument();
    await user.click(chip);
    expect(where()).toBe('?mode=wall');
  });

  it('switches every frame to live data and the light theme, kept in the URL', async () => {
    const user = userEvent.setup();
    renderWall();
    await user.click(screen.getByRole('radio', { name: 'live' }));
    await user.click(screen.getByRole('radio', { name: 'light' }));
    expect(where()).toBe('?mode=wall&data=live&theme=light');
    for (const frame of pageFrames()) expect(frame.getAttribute('src')).toMatch(/\?theme=light&data=live$/);
  });
});

describe('the walk', () => {
  it('replays the journey in one interactive frame, step by step, lighting the move on the map', async () => {
    const user = userEvent.setup();
    renderWall();
    await user.click(screen.getByRole('button', { name: 'Walk' }));
    expect(where()).toBe('?mode=wall&walk=1');
    const panel = screen.getByRole('region', { name: 'Walk' });
    const frame = within(panel).getByTitle(/^reader · normal/) as HTMLIFrameElement;
    expect(frame.getAttribute('src')).toMatch(/walk=1$/);
    expect(frame.style.pointerEvents).toBe('auto');

    const post = vi.spyOn(frame.contentWindow!, 'postMessage');
    const fromFrame = (data: object) => act(() => {
      window.dispatchEvent(new MessageEvent('message', { data, source: frame.contentWindow, origin: window.location.origin }));
    });
    const step = within(panel).getByRole('button', { name: 'Step' });
    expect(step).toBeDisabled();
    fromFrame({ type: WALK_MESSAGE.ready });
    await user.click(step);
    expect(post).toHaveBeenLastCalledWith({ type: WALK_MESSAGE.run, step: 0 }, window.location.origin);
    fromFrame({ type: WALK_MESSAGE.done, step: 0, ok: true });
    await user.click(step);
    expect(post).toHaveBeenLastCalledWith({ type: WALK_MESSAGE.run, step: 1 }, window.location.origin);
    expect(within(panel).getByRole('listitem', { current: 'step' })).toHaveTextContent(WALK[1].label);
    expect(screen.getByTestId('edge-feed-post')).toHaveAttribute('data-current', 'true');
    expect(page('Post')).toHaveAttribute('data-current', 'true');
  });

  it('says out loud when a step fails, and restart reloads the frame at the feed', async () => {
    const user = userEvent.setup();
    renderWall('?mode=wall&walk=1');
    const panel = screen.getByRole('region', { name: 'Walk' });
    const frame = within(panel).getByTitle(/^reader · normal/) as HTMLIFrameElement;
    vi.spyOn(frame.contentWindow!, 'postMessage');
    const fromFrame = (data: object) => act(() => {
      window.dispatchEvent(new MessageEvent('message', { data, source: frame.contentWindow, origin: window.location.origin }));
    });
    fromFrame({ type: WALK_MESSAGE.ready });
    await user.click(within(panel).getByRole('button', { name: 'Play' }));
    expect(within(panel).getByRole('button', { name: 'Pause' })).toBeInTheDocument();
    fromFrame({ type: WALK_MESSAGE.done, step: 0, ok: false, error: 'frame: no a' });
    expect(within(panel).getByRole('status')).toHaveTextContent(/failed.*frame: no a/);
    await user.click(within(panel).getByRole('button', { name: 'Restart' }));
    expect(within(panel).getByTitle(/^reader · normal/)).not.toBe(frame);
    expect(within(panel).getByRole('button', { name: 'Step' })).toBeDisabled();
  });

  it('starts the walk over when the theme changes mid-walk', async () => {
    const user = userEvent.setup();
    renderWall('?mode=wall&walk=1');
    const panel = screen.getByRole('region', { name: 'Walk' });
    const frame = within(panel).getByTitle(/^reader · normal/) as HTMLIFrameElement;
    vi.spyOn(frame.contentWindow!, 'postMessage');
    act(() => {
      window.dispatchEvent(new MessageEvent('message', { data: { type: WALK_MESSAGE.ready }, source: frame.contentWindow, origin: window.location.origin }));
    });
    await user.click(within(panel).getByRole('button', { name: 'Step' }));
    expect(within(panel).getByRole('status')).toHaveTextContent(WALK[0].label);

    await user.click(screen.getByRole('radio', { name: 'light' }));

    expect(within(panel).getByRole('status')).toHaveTextContent('loading the feed');
    expect(within(panel).getByRole('button', { name: 'Step' })).toBeDisabled();
    expect(within(panel).getByTitle(/^reader · normal/)).not.toBe(frame);
  });

  it('ignores messages that are not from its frame', async () => {
    renderWall('?mode=wall&walk=1');
    const panel = screen.getByRole('region', { name: 'Walk' });
    act(() => { window.dispatchEvent(new MessageEvent('message', { data: { type: WALK_MESSAGE.ready }, origin: window.location.origin })); });
    expect(within(panel).getByRole('button', { name: 'Step' })).toBeDisabled();
    fireEvent.click(within(panel).getByRole('button', { name: 'Close walk' }));
    expect(where()).toBe('?mode=wall');
  });
});
