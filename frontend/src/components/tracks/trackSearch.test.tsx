// The table's search params and the suggested fields (Add is the owner's schema edit). Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { briefApi, PRACTICE_KIND, type ThingKindDef } from '../../services/tracks';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { searchParams, withField } from './briefWords';
import TrackFieldSuggestions from './TrackFieldSuggestions';

const kinds: ThingKindDef[] = [
  { kind: 'tool', about: 'one tool', fields: [{ name: 'name', type: 'text', key: true }, { name: 'price', type: 'money' }] },
  { kind: PRACTICE_KIND, fields: [{ name: 'what', type: 'text', key: true }] },
];

describe('search params', () => {
  it('leaves the empty ones out', () => {
    expect(searchParams('  ', '', '')).toEqual({});
    expect(searchParams(' oak handle ', 'Acme Saw', 'product')).toEqual({ q: 'oak handle', entity: 'Acme Saw', entity_type: 'product' });
  });
});

describe('a suggested field added', () => {
  it('goes to its kind, not a key, without the kind code adds', () => {
    const got = withField(kinds, { kind: 'tool', name: 'weight', type: 'number', unit: 'kg', why: 'rows say it' });
    expect(got.map((k) => k.kind)).toEqual(['tool']);
    expect(got[0].fields.at(-1)).toEqual({ name: 'weight', type: 'number', key: false, unit: 'kg' });
  });
  it('is added once', () => {
    const got = withField(kinds, { kind: 'tool', name: 'price', type: 'money', why: 'x' });
    expect(got[0].fields.map((f) => f.name)).toEqual(['name', 'price']);
  });
});

describe('Suggested fields', () => {
  afterEach(() => vi.restoreAllMocks());
  const view = { on: true, version: 1, by: 'haiku' as const, track_version: 1, stale: false, schema: { kinds } };
  const sugg = { on: true, asked_for: 1, at: '2026-11-23T00:00:00Z', fields: [
    { kind: 'tool', name: 'weight', type: 'number' as const, unit: 'kg', about: 'how heavy', why: 'three rows give a weight in the name' },
    { kind: 'tool', name: 'maker', type: 'text' as const, why: 'posts name who makes it' }] };

  it('Add is the owner’s schema edit; Dismiss asks the server', async () => {
    vi.spyOn(briefApi, 'schema').mockResolvedValue(view);
    vi.spyOn(briefApi, 'suggestions').mockResolvedValue(sugg);
    const save = vi.spyOn(briefApi, 'saveSchema').mockResolvedValue({ ...view, version: 2, by: 'owner' });
    const dismiss = vi.spyOn(briefApi, 'dismissField').mockResolvedValue({ ...sugg, fields: [sugg.fields[0]] });
    renderWithProviders(<TrackFieldSuggestions trackId="garden" />, { api: makeFakeApi({}) });
    const user = userEvent.setup();
    expect(await screen.findByText('three rows give a weight in the name')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Dismiss maker/i }));
    await waitFor(() => expect(dismiss).toHaveBeenCalledWith('garden', 'tool', 'maker'));
    await user.click(screen.getByRole('button', { name: /Add weight/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const sent = save.mock.calls[0][1];
    expect(sent.map((k) => k.kind)).toEqual(['tool']);
    expect(sent[0].fields.map((f) => f.name)).toEqual(['name', 'price', 'weight']);
  });

  it('shows nothing when there is nothing to suggest', async () => {
    vi.spyOn(briefApi, 'schema').mockResolvedValue(view);
    const got = vi.spyOn(briefApi, 'suggestions').mockResolvedValue({ ...sugg, fields: [] });
    const { container } = renderWithProviders(<TrackFieldSuggestions trackId="garden" />, { api: makeFakeApi({}) });
    await waitFor(() => expect(got).toHaveBeenCalled());
    expect(container.querySelector('[aria-label="Suggested fields"]')).toBeNull();
  });
});
