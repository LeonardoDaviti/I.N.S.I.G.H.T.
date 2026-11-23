// v10.43: "Your interests": the taps in force by answer, × removes one (undo), the picker adds a thing as "more".
// Synthetic data only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import YourInterests from './YourInterests';
import { interestHref, interestLabel, interestsApi, type TaughtInterest } from '../../services/interests';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const AT = '2026-11-20T10:00:00Z';
const TAUGHT: TaughtInterest[] = [
  { dim: 'thing', key: 'e1', answer: 'more', name: 'Zorblax Engine', origin: 'seed', at: AT },
  { dim: 'kind', key: 'model_release/build', answer: 'less', name: 'builds of an existing model', origin: 'reader', at: AT },
  { dim: 'source', key: 's1', answer: 'none', name: 'Example Blog', origin: 'reader', at: AT },
];

afterEach(() => vi.restoreAllMocks());

describe('labels and links', () => {
  it('names each kind of interest and links things and sources', () => {
    expect(TAUGHT.map(interestLabel)).toEqual(['Zorblax Engine', 'kind: builds of an existing model', 'source: Example Blog']);
    expect(TAUGHT.map(interestHref)).toEqual(['/markx/entities/e1', null, '/read/source/s1']);
  });
});

describe('Your interests (v10.43)', () => {
  it('lists what you raised and lowered, removes one with undo and adds a thing as more', async () => {
    vi.spyOn(interestsApi, 'list').mockResolvedValue({ taught: TAUGHT });
    const teach = vi.spyOn(interestsApi, 'teach').mockResolvedValue({ id: 'x' });
    const find = vi.spyOn(interestsApi, 'find').mockResolvedValue([
      { id: 'e1', name: 'Zorblax Engine', type: 'software', level: null, mentions: 4 },
      { id: 'e2', name: 'Zorblax Cloud', type: 'service', level: null, mentions: 2 },
    ]);
    renderWithProviders(<YourInterests />, { api: makeFakeApi({}) });
    const more = await screen.findByRole('list', { name: 'More of' });
    expect(within(more).getByRole('link', { name: 'Zorblax Engine' })).toHaveAttribute('href', '/markx/entities/e1');
    expect(within(more).getByText('(stated)')).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Less of' })).getByText('kind: builds of an existing model')).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Not a reason' })).getByRole('link', { name: 'source: Example Blog' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Remove kind: builds of an existing model' }));
    expect(teach).toHaveBeenCalledWith({ dim: 'kind', key: 'model_release/build', name: 'builds of an existing model', answer: 'undo' });

    await userEvent.type(screen.getByRole('textbox', { name: 'Find a thing to follow' }), 'zorb');
    const foundList = await screen.findByRole('list', { name: 'Things found' });
    expect(find).toHaveBeenCalledWith('zorb');
    expect(within(foundList).queryByText(/Zorblax Engine/)).toBeNull();   // already followed
    await userEvent.click(within(foundList).getByRole('button', { name: /Zorblax Cloud/ }));
    expect(teach).toHaveBeenLastCalledWith({ dim: 'thing', key: 'e2', name: 'Zorblax Cloud', answer: 'more' });
  });

  it('says nothing is taught yet', async () => {
    vi.spyOn(interestsApi, 'list').mockResolvedValue({ taught: [] });
    renderWithProviders(<YourInterests />, { api: makeFakeApi({}) });
    expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
  });
});
