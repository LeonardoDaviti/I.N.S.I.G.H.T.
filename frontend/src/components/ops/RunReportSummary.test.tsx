import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type { RunReport } from '../../services/api';
import RunReportSummary from './RunReportSummary';
import { runReport, worstRunReport } from './fixtures';

const show = (report: RunReport) => render(<RunReportSummary report={report} />, { wrapper: MemoryRouter });

describe('RunReportSummary', () => {
  it('a run that saved posts: the headline, then each source that delivered, linked to read it', () => {
    show(runReport());
    expect(screen.getByRole('heading', { name: '48 new posts from 2 sources' })).toBeInTheDocument();
    const delivered = screen.getByRole('list', { name: 'New posts by source' });
    const simon = within(delivered).getByRole('link', { name: /Simon Willison’s Weblog/ });
    expect(simon).toHaveAttribute('href', '/read/source/s1');
    expect(simon.closest('li')).toHaveTextContent('30');
  });

  it('shows no zero counts and no raw JSON', () => {
    const { container } = show(runReport());
    expect(screen.queryByRole('list', { name: 'Run counts' })).toBeNull();
    expect(screen.queryByText(/Sources failed|Posts not saved|Fetched posts/)).toBeNull();
    expect(container.querySelector('details, pre')).toBeNull();
    expect(container.textContent).not.toMatch(/posts_inserted|run_id/);
  });

  it('a run that fetched nothing new says how many sources it checked, and lists none', () => {
    show(runReport({ posts_inserted: 0, sources_with_new: 0, inserted_by_source: [] }));
    expect(screen.getByRole('heading', { name: 'Nothing new: 12 sources checked' })).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'New posts by source' })).toBeNull();
  });

  it('a run with failures lists each failed source with its reason, one line each', () => {
    show(worstRunReport());
    expect(screen.getByRole('heading', { name: '1 new post from 1 source, 3 sources failed' })).toBeInTheDocument();
    const items = within(screen.getByRole('list', { name: 'Failed sources' })).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveTextContent('deadlock detected');
    expect(items[2]).toHaveTextContent('No error message');
    expect(screen.getByText('2 posts could not be saved')).toBeInTheDocument();
  });

  it('more sources delivered than the report lists: says how many more', () => {
    show(runReport({ sources_with_new: 25 }));
    expect(screen.getByText('and 23 more sources')).toBeInTheDocument();
  });

  it('long names and errors keep their full text in a title', () => {
    show(worstRunReport());
    expect(screen.getByText(/^Bundesministerium/)).toHaveAttribute('title', expect.stringMatching(/^Bundesministerium/));
  });

  it('an old stored report renders: its enrichment field is ignored', () => {
    show({ ...runReport(), enrichment: { skipped: 'analysis off' } } as RunReport);
    expect(screen.queryByText(/enrich/i)).toBeNull();
  });

  it('nothing due and a busy run render their own headlines', () => {
    const { rerender } = show(runReport({ status: 'nothing_due', sources_fetched: 0, posts_inserted: 0, inserted_by_source: [] }));
    expect(screen.getByRole('heading', { name: 'Nothing was due' })).toBeInTheDocument();
    rerender(<RunReportSummary report={runReport({ status: 'skipped_busy' })} />);
    expect(screen.getByRole('heading', { name: 'Skipped: another run is in progress' })).toBeInTheDocument();
  });
});
