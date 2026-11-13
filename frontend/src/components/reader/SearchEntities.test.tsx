import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';

import SearchEntities from './SearchEntities';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

describe('search entity cards (0184, invented names)', () => {
  it('shows one card a name with its senses, else what it is', () => {
    renderWithProviders(<SearchEntities entities={[
      { id: 'e1', name: 'Vexa', type: 'software', maker: null, posts: 3, voices: 2, what: 'a terminal app',
        senses: [{ id: 'e1', what: 'a terminal app', posts: 3 }, { id: 'e2', what: 'an RSS library', posts: 1 }] },
      { id: 'e3', name: 'Tessel', type: 'software', maker: 'Zentra', posts: 2, voices: 1, what: 'a sync tool' },
    ]} />, { api: makeFakeApi({}) });
    expect(screen.getByText('a terminal app (3) · an RSS library (1)')).toBeInTheDocument();
    expect(screen.getByText('a sync tool')).toBeInTheDocument();
  });
});
