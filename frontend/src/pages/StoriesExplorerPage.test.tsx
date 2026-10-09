import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import StoriesExplorerPage from './StoriesExplorerPage';
import { demoStories, storyDetail, worstDetail, worstStories } from './StoriesExplorerPage.fixtures';
import { makeFakeApi } from '../test/fakeApi';
import { renderWithProviders } from '../test/render';
import type { Api, StoryCard } from '../services/api';

function api(stories: StoryCard[], overrides: Partial<Record<keyof Api, unknown>> = {}) {
  return makeFakeApi({
    getStories: vi.fn().mockResolvedValue({ success: true, stories, total: stories.length }),
    getStory: vi.fn(async (id: string) => {
      const card = stories.find((s) => s.id === id);
      return { success: true, story: card ? (id === worstStories[0].id ? worstDetail : storyDetail(card)) : null };
    }),
    getStoryTimeline: vi.fn(async (id: string) => ({ success: true, story_id: id })),
    ...overrides,
  });
}

function render(fake: Api, route = '/stories') {
  return renderWithProviders(
    <Routes>
      <Route path="/stories" element={<StoriesExplorerPage />} />
    </Routes>,
    { api: fake, route },
  );
}

describe('StoriesExplorerPage', () => {
  it('lists stories as rows and opens the first one in the detail column', async () => {
    const fake = api(demoStories);
    render(fake);
    const nav = await screen.findByRole('navigation', { name: 'Stories' });
    expect(within(nav).getAllByRole('button')).toHaveLength(3);
    expect(await screen.findByRole('heading', { level: 2, name: demoStories[0].canonical_title })).toBeInTheDocument();
    expect(within(nav).getAllByRole('button')[0]).toHaveAttribute('aria-current', 'true');
    expect(screen.getByText('3 stories')).toBeInTheDocument();
    // Status is a glyph plus a word, never colour alone.
    expect(within(nav).getAllByText('active').length).toBeGreaterThan(0);
  });

  it('selecting a row loads that story', async () => {
    const user = userEvent.setup();
    const fake = api(demoStories);
    render(fake);
    const nav = await screen.findByRole('navigation', { name: 'Stories' });
    await user.click(within(nav).getByRole('button', { name: /Smart glasses get a second display vendor/ }));
    expect(await screen.findByRole('heading', { level: 2, name: 'Smart glasses get a second display vendor' })).toBeInTheDocument();
    expect(fake.getStory).toHaveBeenLastCalledWith('story-2');
  });

  it('a status chip refetches with that filter, and "all" clears it', async () => {
    const user = userEvent.setup();
    const fake = api(demoStories);
    render(fake);
    await screen.findByRole('navigation', { name: 'Stories' });
    const status = screen.getByRole('group', { name: 'status' });
    await user.click(within(status).getByRole('button', { name: 'candidate' }));
    expect(within(status).getByRole('button', { name: 'candidate' })).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(fake.getStories).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'candidate' })));
    await user.click(within(status).getByRole('button', { name: 'all' }));
    await waitFor(() => expect(fake.getStories).toHaveBeenLastCalledWith(expect.objectContaining({ status: undefined })));
  });

  it('an unknown status from the URL still gets its own chip', async () => {
    render(api(demoStories), '/stories?status=quarantined');
    const status = await screen.findByRole('group', { name: 'status' });
    expect(within(status).getByRole('button', { name: 'quarantined' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('empty: says so and offers the feed; a failure shows the message and Retry', async () => {
    const user = userEvent.setup();
    const { unmount } = render(api([]));
    expect(await screen.findByText('No stories yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open the feed' })).toBeInTheDocument();
    unmount();

    const getStories = vi.fn()
      .mockResolvedValueOnce({ success: false, error: 'database is down' })
      .mockResolvedValue({ success: true, stories: demoStories, total: 3 });
    render(api(demoStories, { getStories }));
    expect(await screen.findByText('database is down')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('navigation', { name: 'Stories' })).toBeInTheDocument();
  });

  it('worst case: untitled stories, missing anchors and null dates render readable fallbacks', async () => {
    render(api(worstStories));
    const nav = await screen.findByRole('navigation', { name: 'Stories' });
    expect(within(nav).getByText('Untitled story')).toBeInTheDocument();
    expect(within(nav).getByText('12,847 posts')).toBeInTheDocument();
    expect(within(nav).getAllByText('1 update').length).toBeGreaterThan(0);
    expect(await screen.findByText('Untitled anchor post')).toBeInTheDocument();
    expect(screen.getByText('No posts are attached to this update.', { selector: 'p' })).toBeInTheDocument();
  });
});
