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

function setup(
  route = '/',
  sourceName = 'Simon Willison’s Weblog',
  counts: object = { total: 12_847, by_source: { [SOURCE]: 7 }, by_folder: { [FOLDER]: 5 } },
) {
  const api = makeFakeApi({
    getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ source_id: SOURCE })])),
    getUnreadCounts: vi.fn().mockResolvedValue(counts),
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
    expect(within(rail).getByRole('link', { name: /Main feed.*12,847 unread/ })).toBeInTheDocument();
  });

  it('marks the active scope with aria-current="page"', async () => {
    setup(`/read/folder/${FOLDER}`);
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    const active = await within(rail).findByRole('link', { name: /Agentic News/ });
    expect(active).toHaveAttribute('aria-current', 'page');
    expect(within(rail).getByRole('link', { name: /Main feed/ })).not.toHaveAttribute('aria-current');
  });

  it('the scope is "Main feed"; Starred is only a Show choice, and /?filter=starred still opens it (issue 0027)', async () => {
    setup('/?filter=starred');
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    expect(within(rail).queryByRole('link', { name: /Starred/ })).toBeNull();
    expect(within(rail).getByRole('link', { name: /Main feed/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('radio', { name: 'Starred' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^Main feed/);
  });

  it('below md it is a drawer toggled from the toolbar', async () => {
    const user = userEvent.setup();
    setup();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: /open navigation/i }));
    const drawer = await screen.findByRole('dialog', { name: 'Feeds' });
    expect(within(drawer).getByRole('link', { name: /Main feed/ })).toBeInTheDocument();
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

  it('never shows a raw feed URL: URL-named sources get a derived name', async () => {
    setup('/', 'https://rss.arxiv.org/rss/cs.AI');
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    expect(await within(rail).findByRole('link', { name: /^arXiv cs\.AI/ })).toBeInTheDocument();
    expect(within(rail).queryByText(/rss\.arxiv\.org/)).not.toBeInTheDocument();
  });

  it('hides an unread source the directory cannot name instead of "Unknown source"', async () => {
    setup('/', 'Simon Willison’s Weblog', { total: 9, by_source: { [SOURCE]: 7, 'gone-source': 2 }, by_folder: {} });
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    expect(await within(rail).findByRole('link', { name: /Simon Willison’s Weblog.*7 unread/ })).toBeInTheDocument();
    expect(within(rail).queryByText(/Unknown source/)).not.toBeInTheDocument();
    expect(within(rail).queryByRole('link', { name: /2 unread/ })).not.toBeInTheDocument();
  });

  it('has no settings link (the top bar owns sources)', async () => {
    setup();
    const rail = await screen.findByRole('navigation', { name: 'Feeds' });
    expect(within(rail).queryByRole('link', { name: /settings/i })).not.toBeInTheDocument();
  });

  describe('source filter', () => {
    const KAITCHUP = '11111111-0000-4000-8000-00000000000a';
    const CAFE = '11111111-0000-4000-8000-00000000000b';

    function setupDirectory(extraRows: Parameters<typeof healthRow>[0][] = [], byExtra: Record<string, number> = {}, settings: object[] = []) {
      const rows = [
        healthRow({ source_id: SOURCE, display_name: 'Simon Willison’s Weblog' }),
        healthRow({ source_id: KAITCHUP, display_name: 'The Kaitchup', kind: 'substack', platform: 'substack', in_main_digest: false, enabled: false }),
        healthRow({ source_id: CAFE, display_name: 'Café Tech' }),
        ...extraRows.map((row) => healthRow(row)),
      ];
      const getSources = vi.fn().mockResolvedValue({ success: true, total: settings.length, sources: settings });
      const api = makeFakeApi({
        getFeed: vi.fn().mockResolvedValue(feedPage([feedItem({ source_id: SOURCE })])),
        getUnreadCounts: vi.fn().mockResolvedValue({ total: 7, by_source: { [SOURCE]: 7, [CAFE]: 3, ...byExtra }, by_folder: {} }),
        getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
        getSourcesHealth: vi.fn().mockResolvedValue(healthResponse(rows)),
        getSources,
      });
      renderWithProviders(
        <Routes><Route path="/" element={<ReaderPage />} /></Routes>,
        { api, route: '/' },
      );
      return { getSources };
    }

    async function railAndField(firstLink: RegExp = /Simon Willison’s Weblog/) {
      const rail = await screen.findByRole('navigation', { name: 'Feeds' });
      await within(rail).findByRole('link', { name: firstLink });
      return { rail, field: within(rail).getByRole('textbox', { name: 'Filter sources' }) };
    }

    it('searches every source, including ones with nothing unread and outside the main digest', async () => {
      const user = userEvent.setup();
      setupDirectory();
      const { rail, field } = await railAndField();
      expect(within(rail).queryByRole('link', { name: /The Kaitchup/ })).not.toBeInTheDocument();
      await user.type(field, 'KAIT');
      expect(within(rail).getByRole('link', { name: 'The Kaitchup' })).toHaveAttribute('href', `/read/source/${KAITCHUP}`);
      expect(within(rail).queryByRole('link', { name: /Simon Willison/ })).not.toBeInTheDocument();
    });

    it('keeps unread counts on the matches and ignores diacritics', async () => {
      const user = userEvent.setup();
      setupDirectory();
      const { rail, field } = await railAndField();
      await user.type(field, 'cafe');
      expect(within(rail).getByRole('link', { name: /Café Tech.*3 unread/ })).toBeInTheDocument();
      await user.clear(field);
      await user.type(field, 'WILLISÓN');
      expect(within(rail).getByRole('link', { name: /Simon Willison’s Weblog.*7 unread/ })).toBeInTheDocument();
    });

    it('matches the source URL and kind', async () => {
      const user = userEvent.setup();
      const { getSources } = setupDirectory([], {}, [
        { id: KAITCHUP, platform: 'substack', handle_or_url: 'https://kaitchup.substack.com', enabled: false, post_count: 0, settings: { display_name: 'The Kaitchup' } },
      ]);
      const { rail, field } = await railAndField();
      expect(getSources).not.toHaveBeenCalled();
      await user.type(field, 'substack.com');
      expect(await within(rail).findByRole('link', { name: 'The Kaitchup' })).toBeInTheDocument();
      await user.clear(field);
      await user.type(field, 'substack');
      expect(within(rail).getByRole('link', { name: 'The Kaitchup' })).toBeInTheDocument();
    });

    it('says when no source matches', async () => {
      const user = userEvent.setup();
      setupDirectory();
      const { rail, field } = await railAndField();
      await user.type(field, 'zzzz');
      expect(within(rail).getByText('No source matches.')).toBeInTheDocument();
      expect(within(rail).queryByRole('link', { name: /Simon Willison/ })).not.toBeInTheDocument();
    });

    it('Esc and the clear button empty the field', async () => {
      const user = userEvent.setup();
      setupDirectory();
      const { rail, field } = await railAndField();
      await user.type(field, 'cafe');
      await user.keyboard('{Escape}');
      expect(field).toHaveValue('');
      expect(within(rail).getByRole('link', { name: /Simon Willison/ })).toBeInTheDocument();
      await user.type(field, 'cafe');
      await user.click(within(rail).getByRole('button', { name: 'Clear filter' }));
      expect(field).toHaveValue('');
      expect(field).toHaveFocus();
      expect(within(rail).queryByRole('button', { name: 'Clear filter' })).not.toBeInTheDocument();
    });

    it('is reachable by Tab and "/" types into it instead of jumping anywhere', async () => {
      const user = userEvent.setup();
      setupDirectory();
      const { field } = await railAndField();
      field.focus();
      await user.keyboard('/');
      expect(field).toHaveValue('/');
      expect(field).not.toHaveAttribute('tabindex', '-1');
    });

    it('in the drawer, Esc clears the field first and only then closes', async () => {
      const user = userEvent.setup();
      setupDirectory();
      await railAndField();
      await user.click(screen.getByRole('button', { name: /open navigation/i }));
      const drawer = await screen.findByRole('dialog', { name: 'Feeds' });
      const field = within(drawer).getByRole('textbox', { name: 'Filter sources' });
      await user.click(field);
      await user.type(field, 'cafe');
      await user.keyboard('{Escape}');
      expect(field).toHaveValue('');
      expect(screen.getByRole('dialog', { name: 'Feeds' })).toBeInTheDocument();
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('expands the full list inline, all sources, still filterable', async () => {
      const user = userEvent.setup();
      const many = Array.from({ length: 13 }, (_, index) => ({ source_id: `22222222-0000-4000-8000-0000000000${String(index).padStart(2, '0')}`, display_name: `Feed ${index}` }));
      setupDirectory(many, Object.fromEntries(many.map((row, index) => [row.source_id, 20 + index])));
      const { rail, field } = await railAndField(/^Feed 12/);
      expect(within(rail).getAllByRole('link', { name: /^Feed \d+/ })).toHaveLength(12);
      expect(within(rail).queryByRole('link', { name: 'The Kaitchup' })).not.toBeInTheDocument();
      await user.click(within(rail).getByRole('button', { name: 'Show all 16 sources' }));
      expect(within(rail).getAllByRole('link', { name: /^Feed \d+/ })).toHaveLength(13);
      expect(within(rail).getByRole('link', { name: 'The Kaitchup' })).toBeInTheDocument();
      await user.type(field, 'feed 1');
      expect(within(rail).getAllByRole('link', { name: /^Feed \d+/ }).map((link) => link.getAttribute('title'))).toEqual(['Feed 12', 'Feed 11', 'Feed 10', 'Feed 1']);
      await user.clear(field);
      await user.click(within(rail).getByRole('button', { name: 'Show fewer' }));
      expect(within(rail).getAllByRole('link', { name: /^Feed \d+/ })).toHaveLength(12);
    });
  });
});
