import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import DataPanel from './DataPanel';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { ExportInfo, ExportProgress } from '../../services/api';

const INFO: ExportInfo = {
  database_bytes: 1_156_000_000,
  estimate_bytes: 251_000_000,
  estimate_seconds: 28,
  tables: 30,
  login_tables: ['credentials'],
  logins_include: 'the stored test logins, encrypted',
};

afterEach(() => vi.restoreAllMocks());

function setup(progress: (token: string) => Promise<ExportProgress>) {
  const clicks: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clicks.push(this.getAttribute('href') ?? '');
  });
  const getExportProgress = vi.fn(progress);
  renderWithProviders(<DataPanel />, { api: makeFakeApi({ getExportInfo: async () => INFO, getExportProgress }) });
  return { clicks, getExportProgress };
}

describe('DataPanel', () => {
  it('shows the size and estimate, says what logins are, and exports only after the confirmation', async () => {
    const user = userEvent.setup();
    const { clicks } = setup(async () => ({ file_name: 'insight-2026-11-05-1200.zip', bytes: 243_246_920, done: true, error: null }));

    expect(await screen.findByTestId('export-estimate')).toHaveTextContent(
      'The database is 1.2 GB. The zip: about 251 MB, about 28 seconds to write.');
    expect(screen.getByText(/Left out: after a restore/)).toBeInTheDocument();
    await user.click(screen.getByLabelText(/Include stored logins/));
    expect(screen.getByText('Adds the stored test logins, encrypted.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Export everything' }));
    expect(screen.getByRole('alertdialog')).toHaveTextContent('and the stored logins');
    expect(clicks).toEqual([]);
    await user.click(screen.getByRole('button', { name: 'Export' }));
    expect(clicks).toHaveLength(1);
    expect(clicks[0]).toMatch(/^\/api\/export\/everything\?token=[a-z0-9]{24}&logins=true$/);

    expect(await screen.findByText('insight-2026-11-05-1200.zip · 243 MB', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByTestId('restore-command')).toHaveTextContent(
      'python insight_core/db/import_export.py /tmp/insight-2026-11-05-1200.zip --into insight_restored');
  });

  it('cancel exports nothing; a stopped download says it is not whole', async () => {
    const user = userEvent.setup();
    const { clicks } = setup(async () => ({ file_name: 'insight-2026-11-05-1200.zip', bytes: 1000, done: false, error: 'stopped before the end' }));
    await screen.findByTestId('export-estimate');
    await user.click(screen.getByRole('button', { name: 'Export everything' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(clicks).toEqual([]);

    await user.click(screen.getByRole('button', { name: 'Export everything' }));
    await user.click(screen.getByRole('button', { name: 'Export' }));
    expect(clicks[0]).not.toContain('logins');
    expect(await screen.findByText('insight-2026-11-05-1200.zip: stopped before the end', {}, { timeout: 3000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Export everything' })).toBeEnabled());
  });

  it('links the sources list as sources.json', async () => {
    setup(async () => { throw new Error('unused'); });
    expect(screen.getByRole('link', { name: 'Export sources (sources.json)' })).toHaveAttribute('href', '/api/export/sources.json');
  });
});
