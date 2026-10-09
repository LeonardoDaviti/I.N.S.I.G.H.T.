import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import RunReportSummary from './RunReportSummary';
import { runReport, worstRunReport } from './fixtures';

describe('RunReportSummary', () => {
  it('renders the headline, the counts and the per-source new posts', () => {
    render(<RunReportSummary report={runReport()} />);
    expect(screen.getByRole('heading', { name: '48 new posts' })).toBeInTheDocument();
    expect(screen.getByText('Fetched 12 of 78 sources')).toBeInTheDocument();
    const counts = screen.getByRole('list', { name: 'Run counts' });
    expect(within(counts).getByText('Updated').closest('li')).toHaveTextContent('9');
    expect(within(counts).getByText('Sources failed').closest('li')).toHaveTextContent('0');
    expect(screen.getByText('Simon Willison’s Weblog').closest('li')).toHaveTextContent('30');
  });

  it('lists the failures with their stage and error', () => {
    render(<RunReportSummary report={worstRunReport()} />);
    const failures = screen.getByRole('list', { name: 'Failed sources' });
    const items = within(failures).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveTextContent('deadlock detected');
    expect(items[1]).toHaveTextContent('save');
    // an empty error still says something
    expect(items[2]).toHaveTextContent('No error message');
    expect(screen.getByRole('heading', { name: '1 new post, 3 sources failed' })).toBeInTheDocument();
  });

  it('keeps the raw JSON behind a closed disclosure', async () => {
    const { container } = render(<RunReportSummary report={runReport()} />);
    const details = container.querySelector('details');
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute('open');
    const raw = screen.getByText(/"posts_inserted": 48/);
    expect(raw).not.toBeVisible();
    await userEvent.click(screen.getByText('Raw report'));
    expect(raw).toBeVisible();
  });

  it('long names and errors keep their full text in a title', () => {
    render(<RunReportSummary report={worstRunReport()} />);
    const name = screen.getByText(/^Bundesministerium/);
    expect(name).toHaveAttribute('title', expect.stringMatching(/^Bundesministerium/));
  });

  it('nothing due and a busy run render their own headlines', () => {
    const { rerender } = render(<RunReportSummary report={runReport({ status: 'nothing_due', sources_fetched: 0, posts_inserted: 0, decisions: { skip_not_due: 78 } })} />);
    expect(screen.getByRole('heading', { name: 'Nothing was due' })).toBeInTheDocument();
    rerender(<RunReportSummary report={runReport({ status: 'skipped_busy' })} />);
    expect(screen.getByRole('heading', { name: 'Skipped: another run is in progress' })).toBeInTheDocument();
  });
});
