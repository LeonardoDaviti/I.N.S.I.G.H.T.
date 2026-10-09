import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import RunCycleButton from './RunCycleButton';
import { runReport } from './fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

describe('RunCycleButton', () => {
  it('runs a non-forced cycle straight away and reports it', async () => {
    const runIngestionCycle = vi.fn().mockResolvedValue(runReport());
    const onReport = vi.fn();
    renderWithProviders(<RunCycleButton onReport={onReport} />, { api: makeFakeApi({ runIngestionCycle }) });

    await userEvent.click(screen.getByRole('button', { name: 'Run due sources' }));
    await waitFor(() => expect(onReport).toHaveBeenCalledTimes(1));
    expect(runIngestionCycle).toHaveBeenCalledWith(expect.objectContaining({ force: false }));
    expect(onReport.mock.calls[0][0].posts_inserted).toBe(48);
  });

  it('a forced run needs a confirmation; cancel runs nothing', async () => {
    const runIngestionCycle = vi.fn().mockResolvedValue(runReport({ force: true }));
    renderWithProviders(<RunCycleButton />, { api: makeFakeApi({ runIngestionCycle }) });

    await userEvent.click(screen.getByRole('checkbox', { name: /force all/i }));
    await userEvent.click(screen.getByRole('button', { name: 'Force all sources' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent(/ignores cadence and backoff/i);
    expect(runIngestionCycle).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(runIngestionCycle).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Force all sources' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Force fetch every source' }));
    await waitFor(() => expect(runIngestionCycle).toHaveBeenCalledTimes(1));
    expect(runIngestionCycle).toHaveBeenCalledWith(expect.objectContaining({ force: true }));
  });

  it('is busy while the run is in flight', async () => {
    let resolve: (value: unknown) => void = () => {};
    const runIngestionCycle = vi.fn().mockReturnValue(new Promise((r) => { resolve = r; }));
    renderWithProviders(<RunCycleButton />, { api: makeFakeApi({ runIngestionCycle }) });

    await userEvent.click(screen.getByRole('button', { name: 'Run due sources' }));
    const busy = await screen.findByRole('button', { name: /running/i });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute('aria-busy', 'true');
    resolve(runReport());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run due sources' })).toBeEnabled());
  });
});
