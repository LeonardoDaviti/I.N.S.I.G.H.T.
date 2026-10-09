import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import TrackBriefingPanel from './TrackBriefingPanel';
import MilestonesRail from './MilestonesRail';
import VerticalBriefingPage from '../pages/VerticalBriefingPage';
import { apiService } from '../services/api';

// Mark IX briefings restyle: the track briefing, the milestones rail and the
// vertical briefing are monochrome newsletter layouts. State is shape + words.

const CHROMATIC = /\b(?:bg|text|border|ring)-(?:red|blue|indigo|amber|emerald|teal|green|purple|rose|sky|orange|cyan|slate|gray)-\d/;

afterEach(() => {
  vi.restoreAllMocks();
});

const wrap = (ui: React.ReactElement, route = '/') => render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);

describe('TrackBriefingPanel', () => {
  it('reads as a dated issue, flags the fallback stub in words and switches past issues', async () => {
    vi.spyOn(apiService, 'getExperts').mockResolvedValue({ success: true, experts: [{ id: 'e1', name: 'Agentic News', folder_id: 'f1' }] } as never);
    const get = vi.spyOn(apiService, 'getExpertBriefing').mockImplementation(async (_id, date) => ({
      success: true,
      briefing: date ? `Issue of ${date}` : 'Latest text',
      generator: 'fallback',
      posts_processed: 1,
      start_date: '2026-08-30',
      end_date: date ?? '2026-09-29',
      topics: [{ title: 'Pricing shifts', summary: 'Cheaper.', post_ids: ['a'] }],
    }) as never);
    vi.spyOn(apiService, 'getExpertBriefingHistory').mockResolvedValue({
      success: true,
      briefings: [
        { id: 'h1', end_date: '2026-09-29', generator: 'fallback' },
        { id: 'h2', end_date: '2026-09-28', generator: 'gemini' },
      ],
    } as never);
    const user = userEvent.setup();

    const { container } = wrap(<TrackBriefingPanel folderId="f1" />);

    expect(await screen.findByRole('heading', { name: 'Agentic News briefing' })).toBeInTheDocument();
    expect(screen.getByText('Tuesday, 29 September 2026')).toBeInTheDocument();
    expect(screen.getByText('fallback stub, not model analysis')).toBeInTheDocument();
    expect(screen.getAllByText('1 post').length).toBe(2); // header + topic; plural rules, not "1 posts"
    expect(screen.queryByText('1 posts')).not.toBeInTheDocument();
    expect(screen.getByText('Aug 30 – Sep 29, 2026')).toBeInTheDocument();

    const issues = screen.getByRole('navigation', { name: 'Past issues' });
    expect(within(issues).getByRole('button', { name: /Sep 29/ })).toHaveAttribute('aria-current', 'true');
    await user.click(within(issues).getByRole('button', { name: 'Sep 28' }));
    expect(get).toHaveBeenLastCalledWith('e1', '2026-09-28');
    expect(await screen.findByText('Monday, 28 September 2026')).toBeInTheDocument();

    expect(container.innerHTML).not.toMatch(CHROMATIC);
  });

  it('says plainly when no expert is bound', async () => {
    vi.spyOn(apiService, 'getExperts').mockResolvedValue({ success: true, experts: [] } as never);
    wrap(<TrackBriefingPanel folderId="f1" />);
    expect(await screen.findByText('No expert is bound to this folder.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Create one in experts' })).toHaveAttribute('href', '/experts');
  });
});

describe('MilestonesRail', () => {
  const node = (key: string, sources: number) => ({
    node_key: key,
    title: `Model ${key}`,
    occurred_on: '2026-09-22',
    source_count: sources,
    post_count: 1,
    flags: sources === 1 ? ['single_source'] : [],
    comparisons: [],
  });

  it('tells corroborated from single-source nodes by dot shape, and retries a failed evidence drawer', async () => {
    vi.spyOn(apiService, 'getMilestones').mockResolvedValue({
      success: true,
      vendors: [{ vendor: 'Anthropic', node_count: 2, lanes: [{ lane_id: 'l1', lane_name: 'Claude Opus', node_count: 2, nodes: [node('a', 3), node('b', 1)] }] }],
      papers: [],
      stats: { nodes: 2, lanes: 1 },
    } as never);
    const evidence = vi
      .spyOn(apiService, 'getMilestoneNode')
      .mockResolvedValueOnce({ success: false, error: 'Node not found', evidence: [] } as never)
      .mockResolvedValueOnce({ success: true, evidence: [{ post_id: 'p1', title: 'The launch post', role: 'announcement', source_name: 'Blog', published_at: '2026-09-22' }] } as never);
    const user = userEvent.setup();

    const { container } = wrap(<MilestonesRail folderId="f1" />);

    expect(await screen.findByText('Model a')).toBeInTheDocument();
    expect(screen.getByText('2 reached · 1 product line')).toBeInTheDocument();
    const items = screen.getByRole('list', { name: 'Claude Opus milestones' }).querySelectorAll(':scope > li');
    const dot = (li: Element) => li.querySelector('span[aria-hidden="true"]')!.className;
    expect(dot(items[0])).toMatch(/bg-fg/);
    expect(dot(items[1])).toMatch(/bg-bg/);

    await user.click(within(items[0] as HTMLElement).getByText(/evidence \(1\)/));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Node not found');
    await user.click(within(alert).getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('The launch post')).toBeInTheDocument();
    expect(evidence).toHaveBeenCalledTimes(2);

    expect(container.innerHTML).not.toMatch(CHROMATIC);
  });
});

describe('VerticalBriefingPage', () => {
  it('has no hub link or hero, shows track kinds as words and folds long post lists', async () => {
    vi.spyOn(apiService, 'getSourcesWithSettings').mockResolvedValue({ success: true, sources: [{ id: 's1', platform: 'rss', handle_or_url: 'https://arxiv.org/rss/cs.LG', settings: { display_name: 'arXiv cs.LG' } }] } as never);
    vi.spyOn(apiService, 'getVerticalBriefing').mockResolvedValue({
      success: true,
      briefing: 'The briefing text.',
      start_date: '2026-06-01',
      end_date: '2026-09-29',
      posts_processed: 1005,
      tracks: [{ id: 't1', title: 'llama.cpp releases', track_kind: 'project_thread', post_ids: Array.from({ length: 15 }, (_, i) => `p${i}`), unique_post_count: 1, raw_post_count: 12847 }],
      posts: {},
    } as never);
    const user = userEvent.setup();

    const { container } = wrap(<VerticalBriefingPage />, '/briefing/vertical?sourceId=s1');

    await screen.findByText('The briefing text.');
    await waitFor(() => expect(screen.getByText('The briefing text.')).toBeInTheDocument());
    expect(screen.queryByText(/back to hub/i)).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Vertical briefing' })).toBeInTheDocument();
    expect(screen.getAllByText('Jun 1 – Sep 29, 2026').length).toBeGreaterThan(0);
    expect(screen.getByText('project thread')).toBeInTheDocument();
    expect(screen.getByText('1 unique post')).toBeInTheDocument();
    expect(screen.getByText('12,847 raw posts')).toBeInTheDocument();

    await user.click(screen.getByText('llama.cpp releases'));
    expect(screen.getAllByRole('link', { name: /^p\d+$/ })).toHaveLength(12);
    await user.click(screen.getByRole('button', { name: 'show all 15' }));
    expect(screen.getAllByRole('link', { name: /^p\d+$/ })).toHaveLength(15);

    expect(container.innerHTML).not.toMatch(CHROMATIC);
    expect(container.innerHTML).not.toMatch(/gradient/);
  });

  it('reports a failed load as an error notice', async () => {
    vi.spyOn(apiService, 'getSourcesWithSettings').mockResolvedValue({ success: true, sources: [{ id: 's1', platform: 'reddit', handle_or_url: 'r/LocalLLaMA' }] } as never);
    vi.spyOn(apiService, 'getVerticalBriefing').mockResolvedValue({ success: false, error: 'No stored posts found' } as never);
    wrap(<VerticalBriefingPage />, '/briefing/vertical?sourceId=s1');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('No stored posts found');
    expect(screen.getByText('Nothing to read for this source yet.')).toBeInTheDocument();
  });
});
