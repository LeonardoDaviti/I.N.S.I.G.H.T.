import { useCallback, useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiProvider, useApi } from '../../services/ApiContext';
import type { OperationsOverviewResponse } from '../../services/api';
import { ApiError } from '../../lib/apiError';
import { makeFakeApi } from '../../test/fakeApi';
import AppErrorBoundary from '../AppErrorBoundary';
import { EmptyState, ErrorState, LoadingState, Notice } from './index';

/** A minimal data-fetching component in the shape every Mark IX surface takes:
 *  it gets the API from useApi() and renders exactly one of the three states. */
function RecentJobs() {
  const api = useApi();
  const [state, setState] = useState<
    { kind: 'loading' } | { kind: 'error'; error: unknown } | { kind: 'ready'; data: OperationsOverviewResponse }
  >({ kind: 'loading' });

  const load = useCallback(() => {
    setState({ kind: 'loading' });
    api.getOperationsOverview().then(
      (data) => setState({ kind: 'ready', data }),
      (error: unknown) => setState({ kind: 'error', error }),
    );
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === 'loading') return <LoadingState label="Loading jobs" />;
  if (state.kind === 'error') return <ErrorState error={state.error} onRetry={load} />;
  const jobs = state.data.jobs ?? [];
  if (!jobs.length) {
    return <EmptyState title="No jobs yet" description="Run a cycle to see it here." action={{ label: 'Run cycle', onClick: () => {} }} />;
  }
  return <ul>{jobs.map((job) => <li key={job.id}>{job.job_type}</li>)}</ul>;
}

describe('vitest + jsdom + ApiProvider smoke', () => {
  it('a component inside <ApiProvider value={fakeApi}> calls the fake, not the network', async () => {
    const getOperationsOverview = vi.fn().mockResolvedValue({ success: true, jobs: [] });
    render(
      <ApiProvider value={makeFakeApi({ getOperationsOverview })}>
        <RecentJobs />
      </ApiProvider>,
    );

    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
    expect(await screen.findByText('No jobs yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run cycle' })).toBeInTheDocument();
    expect(getOperationsOverview).toHaveBeenCalledTimes(1);
  });

  it('ErrorState shows the ApiError message and Retry calls the API again', async () => {
    const getOperationsOverview = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(503, 'The backend is unavailable. Try again shortly.'))
      .mockResolvedValueOnce({ success: true, jobs: [{ id: 'j1', job_type: 'ingestion_run', status: 'success' }] });
    render(
      <ApiProvider value={makeFakeApi({ getOperationsOverview })}>
        <RecentJobs />
      </ApiProvider>,
    );

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The backend is unavailable. Try again shortly.');
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(await screen.findByText('ingestion_run')).toBeInTheDocument();
    expect(getOperationsOverview).toHaveBeenCalledTimes(2);
  });

  it('the fake API fails loudly when a component calls a method the test did not provide', () => {
    const api = makeFakeApi({});
    expect(() => api.getOperationsOverview()).toThrow(/getOperationsOverview/);
  });
});

describe('AppErrorBoundary', () => {
  function Boom(): never {
    throw new Error('render exploded');
  }

  it('renders a recoverable fallback instead of a blank page', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    let shouldThrow = true;
    function MaybeBoom() {
      if (shouldThrow) return <Boom />;
      return <p>recovered</p>;
    }
    render(
      <AppErrorBoundary>
        <MaybeBoom />
      </AppErrorBoundary>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('render exploded');
    shouldThrow = false;
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(screen.getByText('recovered')).toBeInTheDocument();
    consoleError.mockRestore();
  });
});

describe('Notice: one component per feedback kind (spec F.7)', () => {
  it('status and completion are polite announcements; warning and error are alerts', () => {
    render(
      <>
        <Notice tone="status" title="Run in progress" />
        <Notice tone="completion" title="12 new posts" />
        <Notice tone="warning" title="3 sources in backoff" />
        <Notice tone="error" title="Run failed" message="Run lock held" />
      </>,
    );
    const statuses = screen.getAllByRole('status');
    expect(statuses.map((el) => el.dataset.tone)).toEqual(['status', 'completion']);
    const alerts = screen.getAllByRole('alert');
    expect(alerts.map((el) => el.dataset.tone)).toEqual(['warning', 'error']);
    expect(alerts[1]).toHaveTextContent('Run lock held');
  });

  it('renders an optional action button', async () => {
    const onClick = vi.fn();
    render(<Notice tone="completion" title="Done" action={{ label: 'View report', onClick }} />);
    await userEvent.click(screen.getByRole('button', { name: 'View report' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
