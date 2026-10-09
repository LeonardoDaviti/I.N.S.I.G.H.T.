import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import ReaderPage from '../../pages/ReaderPage';
import { feedPage, feedItem } from './fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { healthResponse, healthRow } from '../ops/fixtures';
import { resetStoredChoices } from '../../hooks/useShortcutPreference';

const FOLDER = 'f8571844-1065-4d96-85b5-1dfd9dc7b111';
const SOURCE = '0a5e90ae-2533-4a31-bf0a-cafd414fc0ce';

function setup(route = '/', sourceName = 'Simon Willison’s Weblog') {
  const api = makeFakeApi({
    getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ source_id: SOURCE })])),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 12_847, by_source: { [SOURCE]: 7 }, by_folder: { [FOLDER]: 5 } }),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [{ id: FOLDER, name: 'Agentic News', sort_order: 1 }] }),
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([healthRow({ source_id: SOURCE, display_name: sourceName })])),
    getPostDetail: vi.fn().mockResolvedValue({ success: true, post: { id: 'x' } }),
  });
  renderWithProviders(
    <Routes>
      <Route path="/" element={<ReaderPage />} />
      <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
    </Routes>,
    { api, route },
  );
  return api;
}

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('ReaderNavRail', () => {
  it('renders unread badges from the counts', async () => {
    setup();
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    expect(await within(rail).findByRole('link', { name: /Agentic News.*5 unread/ })).toBeInTheDocument();
    expect(await within(rail).findByRole('link', { name: /Simon Willison’s Weblog.*7 unread/ })).toBeInTheDocument();
    expect(within(rail).getByRole('link', { name: /All posts.*12,847 unread/ })).toBeInTheDocument();
  });

  it('marks the active scope with aria-current="page"', async () => {
    setup(`/read/folder/${FOLDER}`);
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    const active = await within(rail).findByRole('link', { name: /Agentic News/ });
    expect(active).toHaveAttribute('aria-current', 'page');
    expect(within(rail).getByRole('link', { name: /All posts/ })).not.toHaveAttribute('aria-current');
  });

  it('below md it is a drawer toggled from the toolbar', async () => {
    const user = userEvent.setup();
    setup();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: /open navigation/i }));
    const drawer = await screen.findByRole('dialog', { name: 'Feeds' });
    expect(within(drawer).getByRole('link', { name: /All posts/ })).toBeInTheDocument();
    await user.click(within(drawer).getByRole('link', { name: /Agentic News/ }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('carries only feeds: no second wordmark, no dead hub link, no theme toggle (the top bar owns those)', async () => {
    setup();
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    expect(within(rail).queryByRole('link', { name: /all tools/i })).not.toBeInTheDocument();
    expect(screen.queryByText('INSIGHT')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /switch to (light|dark) theme/i })).not.toBeInTheDocument();
  });

  it('shows URL-named sources without the scheme', async () => {
    setup('/', 'https://rss.arxiv.org/rss/cs.AI');
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    expect(await within(rail).findByRole('link', { name: /^rss\.arxiv\.org\/rss\/cs\.AI/ })).toBeInTheDocument();
  });
});
