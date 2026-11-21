import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import { EntityBrief } from './EntityBrief';
import type { MarkxEntityBrief } from '../../services/markx';

const brief: MarkxEntityBrief = {
  what: [{ thing: 't1', text: 'An experimental mode of the Zentra editor', note: 'preview · by Zentra', sources: 1,
    cites: [{ post: 'p1', n: 1, quote: 'an experimental mode of the editor' }] }],
  how: [{ thing: 't2', text: 'Turned on with a flag', note: '--zen-mode', sources: 1,
    cites: [{ post: 'p2', n: 2, quote: '--zen-mode' }] }],
  results: [{ thing: 't3', text: 'Fewer steps → 12 down to 3', note: 'a benchmark of 40 tasks', sources: 2, who: ['Lab Notes', 'Q Blog'],
    cites: [{ post: 'p2', n: 2, quote: '12 down to 3' }, { post: 'p3', n: 3, quote: 'from 12 to 3' }] }],
  points: [], as_of: '2026-11-20T10:00:00Z',
  posts: [{ id: 'p1', n: 1, title: 'Zen mode', url: null, at: null, source: 'Q Blog' },
    { id: 'p2', n: 2, title: 'How to', url: null, at: null, source: 'Lab Notes' },
    { id: 'p3', n: 3, title: 'Bench', url: null, at: null, source: 'Q Blog' }],
};

describe('EntityBrief (0261)', () => {
  it('shows what it is, how it works and results, each line with superscript cites to its posts', () => {
    render(<MemoryRouter><EntityBrief brief={brief} /></MemoryRouter>);
    const box = screen.getByRole('region', { name: 'Brief' });
    expect(within(box).getByText('What it is')).toBeTruthy();
    expect(within(box).getByText('How it works')).toBeTruthy();
    const results = box.querySelector('[data-brief-part="Results"]') as HTMLElement;
    expect(within(results).getByText(/Lab Notes, Q Blog/)).toBeTruthy();
    const cites = within(results).getAllByRole('link');
    expect(cites.map((a) => a.textContent)).toEqual(['2', '3']);
    expect(cites[0].getAttribute('href')).toBe('/posts/p2');
    expect(cites[0].getAttribute('title')).toContain('12 down to 3');
  });

  it('0269: shows a line note apart from its text, never glued to it with labels', () => {
    render(<MemoryRouter><EntityBrief brief={brief} /></MemoryRouter>);
    const how = screen.getByRole('region', { name: 'Brief' }).querySelector('[data-brief-part="How it works"]') as HTMLElement;
    expect(within(how).getByText('Turned on with a flag', { exact: false })).toBeTruthy();
    expect((how.querySelector('[data-brief-note]') as HTMLElement).textContent).toBe(' — --zen-mode');
  });

  it('shows nothing while off or empty', () => {
    const { container } = render(<MemoryRouter><EntityBrief brief={null} /></MemoryRouter>);
    expect(container.textContent).toBe('');
    const empty = render(<MemoryRouter><EntityBrief brief={{ ...brief, what: [], how: [], results: [] }} /></MemoryRouter>);
    expect(empty.container.textContent).toBe('');
  });
});
