import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import SchedulerDialog from './SchedulerDialog';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

describe('SchedulerDialog: Collect originals (issue 0123)', () => {
  it('is off by default and saves the switch with the tick', async () => {
    const onSave = vi.fn().mockResolvedValue(true);
    renderWithProviders(<SchedulerDialog open config={{ ingest_tick_minutes: 60 }} onClose={() => undefined} onSave={onSave} />, { api: makeFakeApi({}) });
    const toggle = screen.getByRole('switch', { name: 'Collect originals' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ collect_originals: true, ingest_tick_minutes: 60 })));
  });
});
