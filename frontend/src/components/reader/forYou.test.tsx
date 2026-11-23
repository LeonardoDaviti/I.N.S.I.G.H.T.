// v10.42: a News row's why-for-you line and teaching (More / Less because of a thing, the kind, the source; an
// Undo; "Not why"), and the post page's "More or less like this". Synthetic data only.
import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import ForYou from './ForYou';
import PostTeach from '../post/PostTeach';
import type { NewsPersonal } from '../../services/api';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const TEACH = {
  things: [{ id: 'e1', name: 'Example Model 2', type: 'model', answer: null },
    { id: 'e2', name: 'Example Lab', type: 'org', answer: 'more' as const }],
  kind: { key: 'by_other:model', words: "releases for someone else's model", answer: null },
  source: { id: 's1', name: 'Example Channel', answer: null },
};
const PERSONAL: NewsPersonal = {
  p: 1, factor: 1.65, why: 'you follow Example Model 2', teach: TEACH,
  reasons: [{ dim: 'thing', key: 'e1', name: 'Example Model 2', amount: 1, words: 'you follow Example Model 2', by: 'reader', beaten: false },
    { dim: 'kind', key: 'by_other:model', name: 'k', amount: -0.7, words: "you lowered 'k'", by: 'reader', beaten: true }],
};

describe('For you (v10.42)', () => {
  it('names the top reason and teaches More or Less of one thing, the kind or the source, with an Undo', async () => {
    const teachInterest = vi.fn().mockResolvedValue({ id: 'l1' });
    renderWithProviders(<ForYou personal={PERSONAL} row="r1" post="p1" />, { api: makeFakeApi({ teachInterest }) });
    expect(screen.getByText(/you follow Example Model 2/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Teach' }));
    await userEvent.click(screen.getByRole('button', { name: 'Less' }));
    const chips = within(screen.getByRole('group', { name: 'Less because of' })).getAllByRole('button');
    expect(chips.map((c) => c.textContent)).toEqual(['Example Model 2', 'Example Lab (more)',
      "this kind: releases for someone else's model", 'this source: Example Channel']);
    await userEvent.click(chips[2]);
    expect(teachInterest).toHaveBeenCalledWith({ dim: 'kind', key: 'by_other:model', name: "releases for someone else's model",
      answer: 'less', row: 'r1', post: 'p1' });
    expect(await screen.findByRole('status')).toHaveTextContent("Taught: less of releases for someone else's model.");
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(teachInterest).toHaveBeenLastCalledWith(expect.objectContaining({ dim: 'kind', answer: 'undo' }));
  });

  it('"Not why" takes back a tap of yours, and says a learned reason is not one', async () => {
    const teachInterest = vi.fn().mockResolvedValue({ id: 'l1' });
    const { unmount } = renderWithProviders(<ForYou personal={PERSONAL} row="r1" post="p1" />, { api: makeFakeApi({ teachInterest }) });
    await userEvent.click(screen.getByRole('button', { name: 'Not why' }));
    expect(teachInterest).toHaveBeenLastCalledWith(expect.objectContaining({ dim: 'thing', key: 'e1', answer: 'undo' }));
    unmount();
    const learned = { ...PERSONAL, reasons: [{ ...PERSONAL.reasons[0], by: 'learned' as const, words: 'you often read posts about Example Model 2' }] };
    renderWithProviders(<ForYou personal={learned} row="r1" post="p1" />, { api: makeFakeApi({ teachInterest }) });
    await userEvent.click(screen.getByRole('button', { name: 'Not why' }));
    expect(teachInterest).toHaveBeenLastCalledWith(expect.objectContaining({ dim: 'thing', key: 'e1', answer: 'none' }));
  });

  it('shows no why line when the interest moved nothing, only Teach', () => {
    renderWithProviders(<ForYou personal={{ ...PERSONAL, why: null, reasons: [] }} row="r1" post="p1" />, { api: makeFakeApi({}) });
    expect(screen.queryByText('For you')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Teach' })).toBeInTheDocument();
  });

  it("the post page teaches the post's things, its row's kind and its source", async () => {
    const getPostInterest = vi.fn().mockResolvedValue({ post: 'p1', row: 'r1', ...TEACH });
    const teachInterest = vi.fn().mockResolvedValue({ id: 'l1' });
    renderWithProviders(<PostTeach postId="p1" />, { api: makeFakeApi({ getPostInterest, teachInterest }) });
    await userEvent.click(await screen.findByRole('button', { name: 'More' }));
    await userEvent.click(screen.getByRole('button', { name: 'Example Model 2' }));
    expect(teachInterest).toHaveBeenCalledWith(expect.objectContaining({ dim: 'thing', key: 'e1', answer: 'more', row: 'r1', post: 'p1' }));
  });
});
