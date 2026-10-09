import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import AnalystInboxPage from './AnalystInboxPage';
import { batch, demoBatches, item, worstItems } from './AnalystInboxPage.fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api, InboxBatch, InboxItem } from '../services/api';

const items = [
  item(),
  item({ id: 'item-2', status: 'snoozed', target_type: 'story', target_preview: { id: 'story-9', canonical_title: 'Smart glasses thread', story_kind: 'recurring_theme' } }),
];

function api(batches: InboxBatch[], list: InboxItem[], overrides: Partial<Record<keyof Api, unknown>> = {}) {
  return makeFakeApi({
    getSourcesWithSettings: vi.fn().mockResolvedValue({ success: true, sources: [] }),
    getInboxBatches: vi.fn().mockResolvedValue({ success: true, batches, total: batches.length }),
    getInbox: vi.fn(async (id: string) => ({ success: true, batch: batches.find((b) => b.id === id) ?? null, items: list })),
    getInboxItems: vi.fn().mockResolvedValue({ success: true, items: list, total: list.length }),
    getInboxItem: vi.fn(async (id: string) => ({ success: true, item: list.find((i) => i.id === id) ?? null, target: list.find((i) => i.id === id)?.target_preview })),
    getInboxActions: vi.fn().mockResolvedValue({ success: true, actions: [] }),
    ...overrides,
  });
}

function render(fake: Api, route = '/inbox') {
  return renderWithProviders(
    <Routes>
      <Route path="/inbox" element={<AnalystInboxPage />} />
    </Routes>,
    { api: fake, route },
  );
}

describe('AnalystInboxPage', () => {
  it('opens the latest batch and its top item', async () => {
    render(api(demoBatches, items));
    const nav = await screen.findByRole('navigation', { name: 'Inbox items' });
    await waitFor(() => expect(within(nav).getAllByRole('button')).toHaveLength(2));
    expect(await screen.findByRole('heading', { level: 2, name: 'Anthropic ships Claude Code skills' })).toBeInTheDocument();
    expect(screen.getByLabelText('batch')).toHaveValue('batch-1');
    expect(screen.getByText(/18 pending in this batch/)).toBeInTheDocument();
  });

  it('Accept records the action and reports it', async () => {
    const user = userEvent.setup();
    const recordInboxAction = vi.fn().mockResolvedValue({ success: true, item: item({ status: 'accepted' }), side_effects: [{ saved: true }] });
    render(api(demoBatches, items, { recordInboxAction }));
    await screen.findByRole('heading', { level: 2, name: 'Anthropic ships Claude Code skills' });
    await user.click(within(screen.getByRole('group', { name: 'Triage' })).getByRole('button', { name: 'Accept' }));
    expect(recordInboxAction).toHaveBeenCalledWith('item-1', { actionType: 'accept', actorId: 'frontend' });
    expect(await screen.findByText('Recorded: accepted')).toBeInTheDocument();
    expect(screen.getByText('{"saved":true}')).toBeInTheDocument();
  });

  it('changing the status filter refetches the items', async () => {
    const user = userEvent.setup();
    const fake = api(demoBatches, items);
    render(fake);
    await screen.findByRole('navigation', { name: 'Inbox items' });
    await user.selectOptions(screen.getByLabelText('status'), 'snoozed');
    await waitFor(() => expect(fake.getInboxItems).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'snoozed', batchId: 'batch-1' })));
  });

  it('with no batches: an empty state whose action rebuilds the inbox', async () => {
    const user = userEvent.setup();
    const rebuildInbox = vi.fn().mockResolvedValue({ success: true });
    render(api([], [], { rebuildInbox }));
    expect(await screen.findByText('The inbox is empty')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Rebuild inbox' }));
    expect(rebuildInbox).toHaveBeenCalled();
  });

  it('a failed batch load shows the error and Retry', async () => {
    const user = userEvent.setup();
    const getInboxBatches = vi.fn()
      .mockResolvedValueOnce({ success: false, error: 'inbox table missing' })
      .mockResolvedValue({ success: true, batches: demoBatches });
    render(api(demoBatches, items, { getInboxBatches }));
    expect(await screen.findByText('inbox table missing')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('navigation', { name: 'Inbox items' })).toBeInTheDocument();
  });

  it('worst case: missing previews and scores fall back to words, not "undefined"', async () => {
    render(api([batch({ id: 'wb-1', item_count: 12847, pending_count: 12847 })], worstItems), '/inbox?batchId=wb-1');
    const nav = await screen.findByRole('navigation', { name: 'Inbox items' });
    await waitFor(() => expect(within(nav).getAllByRole('button')).toHaveLength(worstItems.length));
    expect(within(nav).getByText('Post without a preview')).toBeInTheDocument();
    expect(within(nav).getByText('Untitled post')).toBeInTheDocument();
    expect(within(nav).getByText('12,847.1')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/undefined|NaN/);
  });
});
