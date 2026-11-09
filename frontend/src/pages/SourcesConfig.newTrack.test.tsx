// v10.12.1: the New track dialog. With Mark X on it also asks what belongs and what doesn't (filled: the track is a
// topic, saved as the track sheet saves it); with Mark X off it asks a name only. Synthetic data only.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SourcesConfig from './SourcesConfig';
import { healthResponse, healthRow } from '../components/ops/fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import { tracksApi, type TrackPage } from '../services/tracks';

const NEW = '00000000-0000-4000-8000-0000000000f9';

function setup(on: boolean) {
  const methods = {
    getSourcesHealth: vi.fn().mockResolvedValue(healthResponse([healthRow({ source_id: 'simon', display_name: 'Example Weblog', folders: [] })])),
    getSources: vi.fn().mockResolvedValue({ success: true, sources: [], total: 0 }),
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: [] }),
    createFolder: vi.fn().mockResolvedValue({ success: true, folder: { id: NEW, name: 'Local AI setups' } }),
    getMarkxOn: on ? vi.fn().mockResolvedValue({ on: true }) : vi.fn().mockRejectedValue(new Error('Not Found')),
  };
  renderWithProviders(<SourcesConfig />, { api: makeFakeApi(methods), route: '/settings/sources' });
  return methods;
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(tracksApi, 'suggestions').mockResolvedValue([]);
});

describe('New track (v10.12.1)', () => {
  it('with Mark X on: what belongs and what doesn’t, saved as a topic', async () => {
    const describe_ = vi.spyOn(tracksApi, 'describe').mockResolvedValue({} as TrackPage);
    const api = setup(true);
    await screen.findByText('Example Weblog');
    await userEvent.click(screen.getByRole('button', { name: 'New track' }));
    expect(await screen.findByText('Describe it in your own words and INSIGHT finds posts from every source.')).toBeInTheDocument();
    const name = screen.getByRole('textbox', { name: 'Track name' });
    expect(name).toHaveAttribute('placeholder', 'For example: Local AI setups');
    await userEvent.type(name, 'Local AI setups');
    await userEvent.type(screen.getByRole('textbox', { name: 'What belongs' }), 'Cheap local AI setups');
    await userEvent.type(screen.getByRole('textbox', { name: 'What doesn’t belong' }), 'cloud GPUs');
    await userEvent.click(screen.getByRole('button', { name: 'Create track' }));
    await waitFor(() => expect(describe_).toHaveBeenCalledWith(NEW, { description: 'Cheap local AI setups', excludes: 'cloud GPUs' }));
    expect(api.createFolder).toHaveBeenCalledWith({ name: 'Local AI setups' });
  });

  it('with Mark X on, a name only: a plain folder', async () => {
    const describe_ = vi.spyOn(tracksApi, 'describe').mockResolvedValue({} as TrackPage);
    const api = setup(true);
    await screen.findByText('Example Weblog');
    await userEvent.click(screen.getByRole('button', { name: 'New track' }));
    await screen.findByRole('textbox', { name: 'What belongs' });
    await userEvent.type(screen.getByRole('textbox', { name: 'Track name' }), 'Prints');
    await userEvent.click(screen.getByRole('button', { name: 'Create track' }));
    await waitFor(() => expect(api.createFolder).toHaveBeenCalled());
    expect(describe_).not.toHaveBeenCalled();
  });

  it('with Mark X off: a name only, as before', async () => {
    setup(false);
    await screen.findByText('Example Weblog');
    await userEvent.click(screen.getByRole('button', { name: 'New track' }));
    expect(await screen.findByText('A track groups sources into their own reading view.')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'What belongs' })).toBeNull();
    expect(screen.getByRole('textbox', { name: 'Track name' })).toHaveAttribute('placeholder', 'For example: Local AI setups');
  });
});
