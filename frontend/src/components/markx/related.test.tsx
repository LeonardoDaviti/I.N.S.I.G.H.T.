// The post page's Related reading, folded and asked only when opened. Synthetic data only.
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXRelated from './MarkXRelated';
import type { MarkxRelated } from '../../services/markx';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const RELATED: MarkxRelated = {
  post_id: 'p1', vector: true,
  items: [
    { id: 'r1', title: 'What is a transformer model?', source: 'Example Site', at: '2026-03-01T10:00:00+00:00', url: null,
      cosine: 0.72, guide: true },
    { id: 'r2', title: '', source: 'Example Channel', at: null, url: null, cosine: 0.66, guide: false },
  ],
};

describe('Related reading (v10.36)', () => {
  it('asks nothing until opened, then lists title · source · date, each opening its post', async () => {
    const getMarkxRelated = vi.fn().mockResolvedValue(RELATED);
    renderWithProviders(<MarkXRelated postId="p1" />, { api: makeFakeApi({ getMarkxRelated }) });
    expect(getMarkxRelated).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('Related reading'));
    const link = await screen.findByRole('link', { name: 'What is a transformer model?' });
    expect(getMarkxRelated).toHaveBeenCalledWith('p1');
    expect(link.getAttribute('href')).toBe('/posts/r1');
    expect(link.parentElement?.textContent).toContain('Example Site');
    expect(link.parentElement?.textContent).toContain('guide');
    expect(screen.getByRole('link', { name: 'a post' }).getAttribute('href')).toBe('/posts/r2');
  });

  it('marks the page a report is about and lists the loose ones under "loosely related" (v10.37)', async () => {
    const data: MarkxRelated = { post_id: 'p1', vector: true, about: 'r1', items: [
      { ...RELATED.items[0], about: true, guide: false },
      { id: 'r3', title: 'A printed GPU rack', source: 'Example Site', at: null, url: null, cosine: 0.58, guide: false,
        loose: true },
    ] };
    renderWithProviders(<MarkXRelated postId="p1" />, {
      api: makeFakeApi({ getMarkxRelated: vi.fn().mockResolvedValue(data) }) });
    await userEvent.click(screen.getByText('Related reading'));
    const page = await screen.findByRole('link', { name: 'What is a transformer model?' });
    expect(page.parentElement?.textContent).toContain('the page it reports');
    const label = screen.getByText('loosely related');
    const loose = screen.getByRole('link', { name: 'A printed GPU rack' });
    expect(label.compareDocumentPosition(loose) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(label.compareDocumentPosition(page) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  it('shows no "loosely related" label when every item is close', async () => {
    renderWithProviders(<MarkXRelated postId="p1" />, {
      api: makeFakeApi({ getMarkxRelated: vi.fn().mockResolvedValue(RELATED) }) });
    await userEvent.click(screen.getByText('Related reading'));
    await screen.findByRole('link', { name: 'What is a transformer model?' });
    expect(screen.queryByText('loosely related')).toBeNull();
  });

  it('says when the post has no vector yet', async () => {
    renderWithProviders(<MarkXRelated postId="p1" />, {
      api: makeFakeApi({ getMarkxRelated: vi.fn().mockResolvedValue({ post_id: 'p1', vector: false, items: [] }) }) });
    await userEvent.click(screen.getByText('Related reading'));
    expect(await screen.findByText(/Not embedded yet/)).toBeTruthy();
  });
});
