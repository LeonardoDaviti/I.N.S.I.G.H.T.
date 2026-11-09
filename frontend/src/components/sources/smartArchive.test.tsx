import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import ArchiveSection from './ArchiveSection';
import SourceDiscoveries from './SourceDiscoveries';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { ArchiveStatusResponse } from '../../services/api';
import { smartArchiveApi, type ArchiveCoverage, type SourceDiscoveries as Found } from '../../services/smartArchive';
import { catalogCoverage, describeCoverage, outcomeWords } from '../../lib/archiveCoverage';

const coverage = (over: Partial<ArchiveCoverage> = {}): ArchiveCoverage => ({
  stored: 19, estimate: 34, platform: 'bearblog', strategy: 'listing', found_more: true, exhausted: false,
  reasons: { sitemap: 'no_sitemap', api: 'api_refused:403' }, ...over,
});

const status = (cov: ArchiveCoverage | null): ArchiveStatusResponse => ({
  success: true,
  archive: { stored_posts: 19, available_posts: 34, last_inspected_at: '2026-11-09T10:00:00Z', resume_ready: false, coverage: cov },
  support: { kind: 'generic_rss', available_basis: 'feed_window', archivable: true, reason: null, unavailable: false, live_fetch_limit: 20 },
  latest_job: null,
});

afterEach(() => vi.restoreAllMocks());

describe('the coverage in words', () => {
  it('says stored of the estimate, the platform, how the rest is read and why not the rest', () => {
    const said = describeCoverage(coverage());
    expect(said.figure).toBe('Stored 19 of ~34');
    expect(said.how).toBe('Built with Bear Blog; the rest is read from the listing pages.');
    expect(said.reasons).toEqual(['the sitemap: no sitemap', "the platform's archive API: refused (HTTP 403)"]);
    expect(describeCoverage(coverage({ found_more: false, platform: 'unknown', estimate: null, strategy: null })))
      .toMatchObject({ figure: 'Stored 19', how: 'Every way to find older posts was tried.' });
    expect(catalogCoverage(coverage())).toBe('19 of ~34 stored');
    expect(catalogCoverage(null)).toBeNull();
    expect(outcomeWords('blocked:429')).toBe('blocked (HTTP 429)');
    expect(outcomeWords('error:ValueError')).toBe('could not be read (ValueError)');
  });
});

describe('the archive section of a measured feed', () => {
  it('shows the coverage instead of "nothing older is reachable", and saves the Web Archive opt-in', async () => {
    const save = vi.spyOn(smartArchiveApi, 'setWebArchive').mockResolvedValue({ on: true });
    renderWithProviders(<ArchiveSection sourceId="s1" />, {
      api: makeFakeApi({ getSourceArchive: vi.fn().mockResolvedValue(status(coverage())), getLinkedPages: vi.fn().mockRejectedValue(new Error('x')) }),
    });
    expect(await screen.findByText('Stored 19 of ~34')).toBeTruthy();
    expect(screen.queryByText(/nothing older is reachable/)).toBeNull();
    expect(screen.getByText('the sitemap: no sitemap')).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox', { name: /Web Archive/ }));
    await waitFor(() => expect(save).toHaveBeenCalledWith('s1', true));
  });

  it('keeps the old note for a feed the smart archiver has not measured', async () => {
    renderWithProviders(<ArchiveSection sourceId="s1" />, {
      api: makeFakeApi({ getSourceArchive: vi.fn().mockResolvedValue(status(null)), getLinkedPages: vi.fn().mockRejectedValue(new Error('x')) }),
    });
    expect(await screen.findByText(/nothing older is reachable/)).toBeTruthy();
    expect(screen.queryByLabelText('Archive coverage')).toBeNull();
  });
});

const found = (over: Partial<Found> = {}): Found => ({
  source_id: 's1',
  sites: [
    { key: 'followed.example', site: 'followed.example', platform: false, state: 'followed', voices: 5, articles: 9, addresses: 9,
      first_linked: '2026-05-01T00:00:00Z', followed_source: { id: 's2', name: 'The followed one', added_at: '2026-07-01T00:00:00Z' } },
    { key: 'open.example', site: 'open.example', platform: false, state: 'open', voices: 3, articles: 1, addresses: 2,
      first_linked: '2026-08-01T00:00:00Z', followed_source: null },
  ],
  followed_from_here: [{ id: 's2', name: 'The followed one', added_at: '2026-07-01T00:00:00Z', key: 'followed.example' }],
  originals: [{ kind: 'collect', url: 'https://open.example/a', outcome: 'collected', post_id: 'p9', story_id: null,
    asked_at: '2026-11-01T00:00:00Z', title: 'A collected page' }],
  entities: [{ id: 'e1', name: 'A named thing', type: 'model', post_id: null, at: null, post_title: null }],
  counts: {},
  discover_counted: true,
  ...over,
});

describe('Discovered through this source', () => {
  it('lists what it discovered: followed first, the sources added after, pages collected, entities named first', async () => {
    vi.spyOn(smartArchiveApi, 'discoveries').mockResolvedValue(found());
    renderWithProviders(<SourceDiscoveries sourceId="s1" />, { api: makeFakeApi({}) });
    expect(await screen.findByText('followed.example')).toBeTruthy();
    expect(screen.getByText('followed · 5 voices · 9 articles linked')).toBeTruthy();
    expect(screen.getByText('not followed · 3 voices · 1 article linked')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'The followed one' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'A collected page' }).getAttribute('href')).toBe('/posts/p9');
    expect(screen.getByRole('link', { name: 'A named thing' }).getAttribute('href')).toBe('/markx/entities/e1');
  });

  it('says why there is nothing yet', async () => {
    vi.spyOn(smartArchiveApi, 'discoveries').mockResolvedValue(found({ sites: [], followed_from_here: [], originals: [], entities: [], discover_counted: false }));
    renderWithProviders(<SourceDiscoveries sourceId="s1" />, { api: makeFakeApi({}) });
    expect(await screen.findByText(/Discover has not counted your links/)).toBeTruthy();
  });
});
