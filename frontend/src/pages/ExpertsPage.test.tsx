import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import ExpertsPage from './ExpertsPage';
import { briefing, expert, folder, worstExperts, worstFolders } from './ExpertsPage.fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api, Expert, Folder } from '../services/api';

const folders = [folder(), folder({ id: 'folder-2', name: 'AI Papers', kind: 'folder', description: null, source_count: 1, post_count: 1 })];

function api(fs: Folder[], es: Expert[], overrides: Partial<Record<keyof Api, unknown>> = {}) {
  return makeFakeApi({
    getFolders: vi.fn().mockResolvedValue({ success: true, folders: fs }),
    getExperts: vi.fn().mockResolvedValue({ success: true, experts: es }),
    getExpertBriefing: vi.fn().mockResolvedValue({ success: false, error: 'none' }),
    getUnreadCounts: vi.fn().mockResolvedValue({ total: 12, by_source: {}, by_folder: { 'folder-1': 12 } }),
    ...overrides,
  });
}

function render(fake: Api) {
  return renderWithProviders(
    <Routes>
      <Route path="/tracks" element={<ExpertsPage />} />
    </Routes>,
    { api: fake, route: '/tracks' },
  );
}

describe('ExpertsPage (tracks)', () => {
  it('lists folders as rows linking to their reading view, with counts and unread', async () => {
    render(api(folders, [expert()]));
    const link = await screen.findByRole('link', { name: 'Agentic News' });
    expect(link).toHaveAttribute('href', '/read/folder/folder-1');
    expect(screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === '12 unread')).toBeInTheDocument();
    expect(screen.getByText('1 source · 1 post', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('1 track · 1 folder · 1 expert')).toBeInTheDocument();
  });

  it('deleting a folder asks first; Cancel keeps it, Delete removes it', async () => {
    const user = userEvent.setup();
    const deleteFolder = vi.fn().mockResolvedValue({ success: true });
    render(api(folders, [], { deleteFolder }));
    await user.click(await screen.findByRole('button', { name: 'Delete folder AI Papers' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(/Delete folder “AI Papers”\?/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(deleteFolder).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Delete folder AI Papers' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete folder' }));
    expect(deleteFolder).toHaveBeenCalledWith('folder-2');
  });

  it('deleting a track says what goes with it: its experts and its milestone lanes; the button is the × danger', async () => {
    const user = userEvent.setup();
    render(api(folders, [expert(), expert({ id: 'expert-2', name: 'Second' })]));
    await user.click(await screen.findByRole('button', { name: 'Delete track Agentic News' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(/Delete track “Agentic News”\?/)).toBeInTheDocument();
    expect(dialog).toHaveTextContent(/2 experts.*deleted/);
    expect(dialog).toHaveTextContent(/milestone lanes/);
    expect(dialog).toHaveTextContent(/sources stay/i);
    const confirm = within(dialog).getByRole('button', { name: 'Delete track' });
    expect(confirm.querySelector('[data-danger-mark]')).toHaveTextContent('×');
  });

  it('Run writes a briefing and opens it', async () => {
    const user = userEvent.setup();
    const runExpert = vi.fn().mockResolvedValue(briefing({ cached: false }));
    render(api(folders, [expert()], { runExpert }));
    await user.click(await screen.findByRole('button', { name: 'Run' }));
    expect(runExpert).toHaveBeenCalledWith('expert-1', { refresh: false });
    expect(await screen.findByText('This week')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Agentic News/, expanded: true })).toBeInTheDocument();
  });

  it('New expert validates in the dialog before calling the API', async () => {
    const user = userEvent.setup();
    const createExpert = vi.fn().mockResolvedValue({ success: true });
    render(api(folders, [], { createExpert }));
    await user.click(await screen.findByRole('button', { name: 'New expert' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Create expert' }));
    expect(within(dialog).getByText('An expert needs a name, a folder and a system prompt.')).toBeInTheDocument();
    expect(createExpert).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText('Name'), 'Papers');
    await user.selectOptions(within(dialog).getByLabelText('Folder'), 'folder-2');
    await user.type(within(dialog).getByLabelText('System prompt'), 'Summarise papers.');
    await user.click(within(dialog).getByRole('button', { name: 'Create expert' }));
    await waitFor(() => expect(createExpert).toHaveBeenCalledWith(expect.objectContaining({ name: 'Papers', folder_id: 'folder-2' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('a failed load shows the error and Retry; empty lists say what to do', async () => {
    const user = userEvent.setup();
    const getFolders = vi.fn()
      .mockResolvedValueOnce({ success: false, folders: [], error: 'folders table missing' })
      .mockResolvedValue({ success: true, folders: [] });
    render(api([], [], { getFolders }));
    expect(await screen.findByText('folders table missing')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No tracks yet')).toBeInTheDocument();
    expect(screen.getByText('No experts yet')).toBeInTheDocument();
  });

  it('worst case: an expert whose folder is gone and a fallback briefing are labelled, counts are formatted', async () => {
    const user = userEvent.setup();
    render(api(worstFolders, worstExperts, {
      getExpertBriefing: vi.fn(async (id: string) => (id === 'we-1' ? briefing({ generator: 'fallback', posts_processed: 12847 }) : { success: false })),
    }));
    expect(await screen.findByText('folder missing')).toBeInTheDocument();
    expect(screen.getByText('12,847 sources · 12,847 posts', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('fallback briefing')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Extremely Thorough/, expanded: false }));
    expect(screen.getByText('Fallback summary, not analysis')).toBeInTheDocument();
    expect(screen.getByText('12,847 posts')).toBeInTheDocument();
  });
});
