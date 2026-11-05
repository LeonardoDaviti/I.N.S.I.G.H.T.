import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import ConnectionsPanel from './ConnectionsPanel';
import { credentials, substackView } from './fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { ApiError } from '../../lib/apiError';
import type { Api } from '../../services/api';

const TOKEN = 'mx-Qx7Lw9ZpRk2vBn4Tj8Hc1Ym6-a3f9';

function setup(methods: Partial<Record<keyof Api, unknown>>) {
  return renderWithProviders(<ConnectionsPanel />, {
    api: makeFakeApi({ getCredentials: vi.fn().mockResolvedValue(credentials(substackView())), ...methods }),
  });
}

describe('Connections → Mark X worker (issue 0086 C)', () => {
  it('is hidden while INSIGHT_MARKX is off (the token route answers 404)', async () => {
    const getMarkxToken = vi.fn().mockRejectedValue(new ApiError(404, 'Not Found'));
    setup({ getMarkxToken });
    await screen.findByText('Substack');
    await waitFor(() => expect(getMarkxToken).toHaveBeenCalled());
    expect(screen.queryByText('Mark X worker')).not.toBeInTheDocument();
  });

  it('generates a token and shows it once; the cache keeps only its state', async () => {
    const createMarkxToken = vi.fn().mockResolvedValue({ token: TOKEN, set: true, last4: 'a3f9', updated_at: '2026-11-05T10:00:00Z' });
    const { queryClient } = setup({
      getMarkxToken: vi.fn().mockResolvedValue({ set: false, last4: null, updated_at: null }), createMarkxToken,
    });
    expect(await screen.findByText('Mark X worker')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Mark X worker' })).getByText('not set')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'generate token' }));
    expect(await screen.findByTestId('markx-token')).toHaveTextContent(TOKEN);
    expect(screen.getByText(/It is not shown again/)).toBeInTheDocument();
    expect(screen.getByText('set · ••••a3f9')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'replace token' })).toBeInTheDocument();
    expect(JSON.stringify(queryClient.getQueryData(['markx-token']))).not.toContain(TOKEN);
  });

  it('a set token shows its last four characters, never itself; a failed generation says why', async () => {
    const createMarkxToken = vi.fn().mockRejectedValue(new ApiError(400, 'Secrets cannot be stored: no key'));
    setup({ getMarkxToken: vi.fn().mockResolvedValue({ set: true, last4: 'zz99', updated_at: '2026-11-04T10:00:00Z' }),
      createMarkxToken });
    expect(await screen.findByText('set · ••••zz99')).toBeInTheDocument();
    expect(screen.queryByTestId('markx-token')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'replace token' }));
    expect(await screen.findByText(/Could not generate a token: Secrets cannot be stored/)).toBeInTheDocument();
  });
});
