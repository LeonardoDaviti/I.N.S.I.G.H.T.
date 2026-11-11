// 0163 (later developments, Shadow): the story page's "Later" and the entity page's "Later developments": the rows
// judged development first, the rest folded, the four label buttons, and "Stop following this story". Synthetic data.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { EntityLater, StoryLater, markxLaterApi, type MarkxLaterRow, type MarkxStoryLater } from './MarkXLater';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';

const ROW: MarkxLaterRow = {
  id: 'l1', story: 's1', headline: 'A study of widgets', post: 'p1', title: 'I tried the widget method on another model',
  url: null, source: 'Example Blog', at: '2026-09-01T10:00:00+00:00', days_after: 77, trig: ['E', 'L'], entity: 'e1',
  entity_name: 'A Study of Widgets', verdict: 'development', runs: ['development', 'development', 'retold'], label: null,
};
const PAGE: MarkxStoryLater = {
  stories: [{ story: 's1', headline: 'A study of widgets', long_lived: true, following: true,
    subjects: [{ id: 'e1', name: 'A Study of Widgets' }] }],
  items: [ROW, { ...ROW, id: 'l2', post: 'p2', title: 'A recap', verdict: 'retold', runs: ['retold', 'retold', 'related'] },
    { ...ROW, id: 'l3', post: 'p3', title: 'Just in', verdict: null, runs: [] }],
  counts: { candidates: 3, development: 1, retold: 1, waiting: 1 },
  precision: { labelled: 0, development: 0, precision: null },
  news: false,
};

afterEach(() => vi.restoreAllMocks());

describe('Later (0163)', () => {
  it('shows the developments first with the days after, the trigger and the runs, the rest folded', async () => {
    vi.spyOn(markxLaterApi, 'story').mockResolvedValue(PAGE);
    renderWithProviders(<StoryLater storyId="mx1" />, { api: makeFakeApi({}) });
    const region = await screen.findByRole('region', { name: 'Later' });
    expect(region).toHaveTextContent('Following A Study of Widgets');
    expect(region).toHaveTextContent('Shadow only, not on News · none labelled yet');
    const dev = within(region).getByRole('list', { name: 'Developments' });
    expect(within(dev).getAllByRole('listitem')).toHaveLength(1);
    expect(dev).toHaveTextContent('77 days after · Example Blog · names A Study of Widgets, links A Study of Widgets · development (2 of 3 runs development)');
    expect(within(dev).getByRole('link', { name: 'I tried the widget method on another model' })).toHaveAttribute('href', '/posts/p1');
    expect(region).toHaveTextContent('2 other later posts');
    const rest = within(region).getByRole('list', { name: 'Other later posts', hidden: true });
    expect(rest).toHaveTextContent('waiting for Haiku');
  });

  it('labels a row and stops following the story', async () => {
    vi.spyOn(markxLaterApi, 'story').mockResolvedValue({ ...PAGE, items: [ROW] });
    const label = vi.spyOn(markxLaterApi, 'label')
      .mockResolvedValue({ id: 'x', answer: 'related', label: 'related', precision: { labelled: 1, development: 0, precision: 0 } });
    const follow = vi.spyOn(markxLaterApi, 'follow').mockResolvedValue({ story: 's1', following: false });
    renderWithProviders(<StoryLater storyId="s1" />, { api: makeFakeApi({}) });
    const group = await screen.findByRole('group', { name: 'What is this?' });
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(['development', 'retold', 'related', 'unrelated']);
    await userEvent.click(within(group).getByRole('button', { name: 'related' }));
    expect(label).toHaveBeenCalledWith('l1', 'related');
    expect(await within(group).findByText('you said related')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Stop following this story' }));
    expect(follow).toHaveBeenCalledWith('s1', false);
  });

  it('shows nothing for a story that is not long-lived and has no rows', async () => {
    const story = vi.spyOn(markxLaterApi, 'story').mockResolvedValue({ ...PAGE, items: [],
      stories: [{ ...PAGE.stories[0], long_lived: false, following: false, subjects: [] }] });
    renderWithProviders(<StoryLater storyId="s1" />, { api: makeFakeApi({}) });
    await waitFor(() => expect(story).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole('region', { name: 'Later' })).not.toBeInTheDocument();
  });

  it('lists an entity’s later developments with the story they follow', async () => {
    vi.spyOn(markxLaterApi, 'entity').mockResolvedValue({ entity: 'e1', items: [ROW], counts: { candidates: 1, development: 1 } });
    renderWithProviders(<EntityLater entityId="e1" />, { api: makeFakeApi({}) });
    const region = await screen.findByRole('region', { name: 'Later developments' });
    expect(within(region).getByRole('link', { name: 'A study of widgets' })).toHaveAttribute('href', '/posts/s1');
    expect(region).toHaveTextContent('77 days after');
  });
});
