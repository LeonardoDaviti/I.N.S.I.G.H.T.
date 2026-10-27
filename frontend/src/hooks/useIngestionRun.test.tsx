import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, renderHook, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { Toaster } from 'sonner';

import { useIngestionRun } from './useIngestionRun';
import { ApiProvider } from '../services/ApiContext';
import { makeFakeApi } from '../test/fakeApi';
import { makeTestQueryClient } from '../test/render';
import { runReport } from '../components/ops/fixtures';
import { ApiError } from '../lib/apiError';
import type { Api } from '../services/api';

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function setup(api: Api) {
  const queryClient = makeTestQueryClient();
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ApiProvider value={api}>
          <MemoryRouter>
            {children}
            <Where />
            <Toaster />
          </MemoryRouter>
        </ApiProvider>
      </QueryClientProvider>
    );
  }
  const hook = renderHook(() => useIngestionRun(), { wrapper: Wrapper });
  const invalidatedKeys = () => invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  return { ...hook, invalidatedKeys };
}

describe('useIngestionRun', () => {
  it('on success invalidates unread counts and source health, never the feed', async () => {
    const fetchSourceNow = vi.fn().mockResolvedValue(runReport({ posts_inserted: 3, sources_with_new: 1 }));
    const { result, invalidatedKeys } = setup(makeFakeApi({ fetchSourceNow }));

    let report: unknown;
    await act(async () => {
      report = await result.current.run({ kind: 'source', id: 's1', name: 'Simon' });
    });

    expect(fetchSourceNow).toHaveBeenCalledWith('s1', expect.any(Object));
    expect((report as { posts_inserted: number }).posts_inserted).toBe(3);
    const keys = invalidatedKeys();
    expect(keys).toContain(JSON.stringify(['unread-counts']));
    expect(keys).toContain(JSON.stringify(['sources-health']));
    expect(keys.some((key) => key.startsWith('["feed"'))).toBe(false);
    expect(await screen.findByText('3 new posts from 1 source')).toBeInTheDocument();
  });

  it('routes each target to its API method', async () => {
    const runIngestionCycle = vi.fn().mockResolvedValue(runReport());
    const fetchFolderNow = vi.fn().mockResolvedValue(runReport());
    const { result } = setup(makeFakeApi({ runIngestionCycle, fetchFolderNow }));

    await act(async () => { await result.current.run({ kind: 'all', force: true }); });
    await act(async () => { await result.current.run({ kind: 'folder', id: 'f1', name: 'AI' }); });

    expect(runIngestionCycle).toHaveBeenCalledWith(expect.objectContaining({ force: true }));
    expect(fetchFolderNow).toHaveBeenCalledWith('f1', expect.any(Object));
  });

  it('tracks which target is running', async () => {
    let resolve: (value: unknown) => void = () => {};
    const fetchSourceNow = vi.fn().mockReturnValue(new Promise((r) => { resolve = r; }));
    const { result } = setup(makeFakeApi({ fetchSourceNow }));

    let pending: Promise<unknown> = Promise.resolve();
    act(() => { pending = result.current.run({ kind: 'source', id: 's1' }); });
    await waitFor(() => expect(result.current.isRunning({ kind: 'source', id: 's1' })).toBe(true));
    expect(result.current.isRunning({ kind: 'source', id: 's2' })).toBe(false);
    await act(async () => { resolve(runReport()); await pending; });
    expect(result.current.isRunning({ kind: 'source', id: 's1' })).toBe(false);
  });

  it('the toast\'s View job opens the job in Sources → ingestion → jobs', async () => {
    const fetchSourceNow = vi.fn().mockImplementation(async (_id, { onAccepted }) => {
      onAccepted({ job_id: 'job-9' });
      return runReport({ run_id: 'run-9' });
    });
    const { result } = setup(makeFakeApi({ fetchSourceNow }));
    await act(async () => { await result.current.run({ kind: 'source', id: 's1', name: 'Job nine feed' }); });
    const toast = (await screen.findByText(/Job nine feed/)).closest('li') as HTMLElement;
    fireEvent.click(within(toast).getByRole('button', { name: 'View job' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/settings/sources?tab=ingestion&sub=jobs&job=job-9');
  });

  it('a failed request shows an error toast and resolves null instead of throwing', async () => {
    const fetchSourceNow = vi.fn().mockRejectedValue(new ApiError(503, 'job tracking unavailable'));
    const { result } = setup(makeFakeApi({ fetchSourceNow }));

    let report: unknown = 'unset';
    await act(async () => { report = await result.current.run({ kind: 'source', id: 's1' }); });
    expect(report).toBeNull();
    expect(await screen.findByText('job tracking unavailable')).toBeInTheDocument();
    expect(result.current.lastError).toBeTruthy();
  });
});
