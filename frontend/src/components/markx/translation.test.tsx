import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MarkXTranslation from './MarkXTranslation';
import MarkXPanel from './MarkXPanel';
import type { MarkxTranslationView } from '../../services/api';
import type { MarkxPostPanel } from '../../services/markx';
import { makeFakeApi as makeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

// the translation methods live outside createApi (api.ts' 0130 D block), so the fake takes them untyped
const makeFakeApi = (methods: Record<string, unknown>) => makeApi(methods as Parameters<typeof makeApi>[0]);
const at = new Date().toISOString();
const view = (over: Partial<MarkxTranslationView> = {}): MarkxTranslationView => ({
  post_id: 'p1', lang: 'ru', foreign: true, task: null, translation: null, label: null, ...over,
});
const asked = view({ task: { id: 't1', status: 'open', guide: 'translate-v2', error: null } });
const done = (label: MarkxTranslationView['label'] = null) => view({
  task: { id: 't1', status: 'answered', guide: 'translate-v2', error: null }, label,
  translation: { title_en: 'Acme released Widget 4.1', text_en: 'First paragraph.\n\nSecond paragraph.', guide: 'translate-v2',
    model: 'claude-haiku-5-5', at },
});

describe('a post translated by Haiku (0130 D)', () => {
  it('shows nothing on an English post or one of unknown language', async () => {
    const getMarkxTranslation = vi.fn().mockResolvedValue(view({ lang: 'en', foreign: false }));
    const { container } = renderWithProviders(<MarkXTranslation postId="p1" />, { api: makeFakeApi({ getMarkxTranslation }) });
    await waitFor(() => expect(getMarkxTranslation).toHaveBeenCalledWith('p1'));
    expect(container.textContent).toBe('');
    expect(screen.queryByRole('button', { name: 'Translate' })).toBeNull();
  });

  it('asks on a tap, then says the next worker run answers it', async () => {
    const getMarkxTranslation = vi.fn().mockResolvedValue(view());
    const askMarkxTranslation = vi.fn().mockResolvedValue({ task_id: 't1', new: true, view: asked });
    renderWithProviders(<MarkXTranslation postId="p1" />, { api: makeFakeApi({ getMarkxTranslation, askMarkxTranslation }) });
    expect(await screen.findByText(/Russian: Haiku translates it on the next worker run/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Translate' }));
    expect(askMarkxTranslation).toHaveBeenCalledWith('p1');
    expect(await screen.findByText('Translation asked: the next worker run answers it.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Translate' })).toBeNull();
  });

  it('shows the English under the original, marked, with ✓ / ✗ that a second tap takes back', async () => {
    const getMarkxTranslation = vi.fn().mockResolvedValue(done());
    const labelMarkxTranslation = vi.fn().mockResolvedValueOnce(done('right')).mockResolvedValueOnce(done(null));
    renderWithProviders(<MarkXTranslation postId="p1" />, { api: makeFakeApi({ getMarkxTranslation, labelMarkxTranslation }) });
    expect(await screen.findByText(/Translated by Haiku from Russian/)).toBeInTheDocument();
    expect(screen.getByText('Acme released Widget 4.1')).toBeInTheDocument();
    expect(screen.getByText(/First paragraph\.\s+Second paragraph\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '✓ right' }));
    expect(labelMarkxTranslation).toHaveBeenLastCalledWith('p1', 'right');
    await waitFor(() => expect(screen.getByRole('button', { name: '✓ right' })).toHaveAttribute('aria-pressed', 'true'));
    await userEvent.click(screen.getByRole('button', { name: '✓ right' }));
    expect(labelMarkxTranslation).toHaveBeenLastCalledWith('p1', 'undo');
    await waitFor(() => expect(screen.getByRole('button', { name: '✓ right' })).toHaveAttribute('aria-pressed', 'false'));
  });

  it('offers to ask again when Haiku failed three times', async () => {
    const getMarkxTranslation = vi.fn().mockResolvedValue(view({
      task: { id: 't1', status: 'failed', guide: 'translate-v2', error: 'the number 2 of the post is not in the translation' } }));
    renderWithProviders(<MarkXTranslation postId="p1" />, { api: makeFakeApi({ getMarkxTranslation }) });
    expect(await screen.findByText(/Haiku could not translate it: the number 2/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask again' })).toBeInTheDocument();
  });

  it('has its line in the Mark X panel', async () => {
    const panel: MarkxPostPanel = { post_id: 'p1', read: false, reading: null, entities: [], stories: [], connections: [] };
    const getMarkxTranslation = vi.fn().mockResolvedValue(done('wrong'));
    renderWithProviders(<MarkXPanel postId="p1" />, {
      api: makeFakeApi({ getMarkxPost: vi.fn().mockResolvedValue(panel), getMarkxTranslation }),
    });
    await userEvent.click(screen.getByText('Mark X'));
    expect(await screen.findByText(/Translated by Haiku \(translate-v2\), shown under the post · you: ✗ wrong/)).toBeInTheDocument();
  });
});
