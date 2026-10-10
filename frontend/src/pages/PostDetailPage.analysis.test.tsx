import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { makeFakeApi } from '../test/fakeApi';
import { POST_ID, baseApi, renderPost as render, rssPost } from './PostDetailPage.testkit';

// The analysis version of the post page (VITE_INSIGHT_ANALYSIS=on, spec §9).
vi.mock('../lib/features', () => ({ ANALYSIS_ENABLED: true }));

describe('PostDetailPage with analysis on: summary', () => {
  it('shows a request error as a dismissible notice', async () => {
    const user = userEvent.setup();
    const getPostSummary = vi.fn().mockResolvedValue({ success: false, error: 'LLM quota exhausted' });
    render(baseApi(rssPost(), { getPostSummary }));
    await user.click(await screen.findByRole('button', { name: 'Generate summary' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('LLM quota exhausted');
    await user.click(within(alert).getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('PostDetailPage intelligence inspector', () => {
  it('stays closed and unfetched until Inspect opens it in a sheet', async () => {
    const user = userEvent.setup();
    const getPostEvidence = vi.fn().mockResolvedValue({
      success: true,
      evidence: { post: { url_host: 'simonwillison.net', normalized_url: 'https://simonwillison.net/x' }, artifacts: [], relations: { outgoing: [], incoming: [] } },
    });
    render(baseApi(rssPost(), { getPostEvidence }));
    await screen.findByRole('heading', { level: 1 });
    expect(getPostEvidence).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Inspect' }));
    const sheet = await screen.findByRole('dialog', { name: 'Post intelligence' });
    expect(getPostEvidence).toHaveBeenCalledWith(POST_ID);
    expect(await within(sheet).findByText('https://simonwillison.net/x')).toBeInTheDocument();
    expect(within(sheet).getByRole('tab', { name: 'evidence' })).toHaveAttribute('aria-selected', 'true');
  });
});

describe('PostDetailPage highlights', () => {
  it('marks highlights with a neutral tint and underlines the ones the summary used', async () => {
    const api = makeFakeApi({
      getPostDetail: vi.fn().mockResolvedValue({
        success: true,
        post: rssPost(),
        summary: { summary_markdown: 'Short version.', model: 'test-model', one_sentence_takeaway: 'Agents won the year.' },
        summary_references: [{ highlight_id: 'h2' }],
        highlights: [
          { id: 'h1', highlight_text: 'closing keynote' },
          { id: 'h2', highlight_text: 'Agents shipped everywhere' },
        ],
        reader_state: null,
      }),
      getPostTimeline: vi.fn().mockResolvedValue({ success: true, timeline: null, related_candidates: [] }),
      recordPostOpen: vi.fn().mockResolvedValue({ success: true }),
      recordPostReadingSession: vi.fn().mockResolvedValue({ success: true }),
    });
    render(api);
    const article = await screen.findByRole('article', { name: 'Post content' });
    const marks = article.querySelectorAll('mark');
    expect(Array.from(marks, (mark) => mark.textContent)).toEqual(['closing keynote', 'Agents shipped everywhere']);
    expect(marks[0]).not.toHaveAttribute('data-used-in-summary');
    expect(marks[1]).toHaveAttribute('data-used-in-summary', 'true');
    for (const mark of marks) {
      expect(mark.className).not.toMatch(/yellow|rgba/);
    }
    // The summary is open because it exists, with its takeaway first.
    expect(screen.getByText('Agents won the year.')).toBeVisible();
  });
});

describe('PostDetailPage with analysis on: story', () => {
  it('loads the story timeline only when its panel is opened', async () => {
    const user = userEvent.setup();
    const api = baseApi(rssPost());
    render(api);
    await screen.findByRole('heading', { level: 1 });
    expect(api.getPostTimeline).not.toHaveBeenCalled();
    await user.click(screen.getByText('Story'));
    await waitFor(() => expect(api.getPostTimeline).toHaveBeenCalledWith(POST_ID, false));
  });
});
