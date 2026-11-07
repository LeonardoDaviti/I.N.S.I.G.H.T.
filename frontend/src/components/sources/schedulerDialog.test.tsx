import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import SchedulerDialog from './SchedulerDialog';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

describe('SchedulerDialog: Collect originals (issues 0123, 0126)', () => {
  it('is on by default and saves the switch with the tick', async () => {
    const onSave = vi.fn().mockResolvedValue(true);
    renderWithProviders(<SchedulerDialog open config={{ ingest_tick_minutes: 60 }} onClose={() => undefined} onSave={onSave} />, { api: makeFakeApi({}) });
    const toggle = screen.getByRole('switch', { name: 'Collect originals' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ collect_originals: false, ingest_tick_minutes: 60 })));
  });

  it('shows the stored choice: switched off stays off', () => {
    renderWithProviders(<SchedulerDialog open config={{ ingest_tick_minutes: 60, collect_originals: false }} onClose={() => undefined} onSave={vi.fn()} />, { api: makeFakeApi({}) });
    expect(screen.getByRole('switch', { name: 'Collect originals' })).toHaveAttribute('aria-checked', 'false');
  });
});
