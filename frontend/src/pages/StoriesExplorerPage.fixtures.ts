import type { Api, Post, StoryCard, StoryDetail, StoryUpdateEntry } from '../services/api';

/**
 * Story fixtures (break-ui, spec §F.7): `demo` is kind data, `worst` spreads the
 * realistic failures over the first rows (long and missing titles, an unbreakable
 * URL, RTL, CJK and emoji text, 0/1/12,847 counts, null and future dates, unknown
 * vocabulary), `empty`, `one` and `huge` cover the list lengths.
 */

export const STORY_FIXTURE_NAMES = ['worst', 'empty', 'one', 'huge'] as const;

const UNBREAKABLE_URL =
  'https://northwind-industries-holdings.example.com/press/2026/10/09/announcing-the-general-availability-of-the-agent-orchestration-runtime-v2-final-final.html';

function post(overrides: Partial<Post> = {}): Post {
  return {
    id: 'post-1',
    title: 'Anthropic ships Claude Code skills',
    content: '',
    source: 'Simon Willison',
    source_display_name: 'Simon Willison',
    platform: 'rss',
    url: 'https://simonwillison.net/2026/Oct/9/skills/',
    published_at: '2026-10-09T08:15:00Z',
    ...overrides,
  };
}

export function story(overrides: Partial<StoryCard> = {}): StoryCard {
  return {
    id: 'story-1',
    canonical_title: 'Coding agents get a skills format',
    canonical_summary: 'Several vendors converge on a folder-of-instructions format for agent skills.',
    story_kind: 'project_thread',
    status: 'active',
    anchor_post_id: 'post-1',
    anchor_confidence: 0.82,
    first_seen_at: '2026-10-01T09:00:00Z',
    last_seen_at: '2026-10-09T08:15:00Z',
    created_by_method: 'resolver',
    resolution_version: 'v3',
    updated_at: '2026-10-09T08:20:00Z',
    post_count: 12,
    update_count: 3,
    ...overrides,
  };
}

function update(overrides: Partial<StoryUpdateEntry> = {}): StoryUpdateEntry {
  return {
    id: 'update-1',
    story_id: 'story-1',
    update_date: '2026-10-09',
    title: 'A second vendor adopts the format',
    summary: 'The format now ships in two agent harnesses.',
    importance_score: 0.7,
    posts: [{ story_update_id: 'update-1', post_id: 'post-1', post: post() }],
    ...overrides,
  };
}

export function storyDetail(card: StoryCard, overrides: Partial<StoryDetail> = {}): StoryDetail {
  return {
    ...card,
    anchor_post: { id: 'post-1', title: 'Anthropic ships Claude Code skills', url: 'https://simonwillison.net/2026/Oct/9/skills/', platform: 'rss', source_display_name: 'Simon Willison', published_at: '2026-10-09T08:15:00Z' },
    posts_by_role: {
      anchor: [{ story_id: card.id, post_id: 'post-1', role: 'anchor', relevance_score: 0.94, anchor_score: 0.82, evidence_weight: 0.6, post: post() }],
      supporting: [{ story_id: card.id, post_id: 'post-2', role: 'supporting', relevance_score: 0.71, anchor_score: 0.1, evidence_weight: 0.3, post: post({ id: 'post-2', title: 'Skills, explained', source_display_name: 'Latent Space' }) }],
    },
    timeline: [update(), update({ id: 'update-2', update_date: '2026-10-02', title: 'The format is announced', importance_score: 0.9 })],
    ...overrides,
  };
}

export const demoStories: StoryCard[] = [
  story(),
  story({ id: 'story-2', canonical_title: 'Smart glasses get a second display vendor', story_kind: 'recurring_theme', post_count: 5, update_count: 1, last_seen_at: '2026-10-08T10:00:00Z' }),
  story({ id: 'story-3', canonical_title: 'Telegram channel migration', story_kind: 'one_off_update', status: 'candidate', post_count: 1, update_count: 0, anchor_confidence: undefined }),
];

export const worstStories: StoryCard[] = [
  story({
    id: 'w-1',
    canonical_title:
      'OpenAI reports Navier-Stokes singularity find, a contender for second ever Millennium Prize awarded, overshadowing Cognition’s $48B Series E, Mistral’s $24B Series D, Meta’s Muse agent, and GPT Image 2.5',
    canonical_summary:
      'A very long summary that keeps going because the resolver concatenated three sources into one canonical paragraph without any line breaks, which is exactly what happens when a story is merged twice and nobody rewrites the summary afterwards.',
    post_count: 12847,
    update_count: 1,
  }),
  story({ id: 'w-2', canonical_title: UNBREAKABLE_URL, canonical_summary: null, story_kind: undefined, status: undefined, post_count: 0, update_count: 0, last_seen_at: null }),
  story({ id: 'w-3', canonical_title: 'إطلاق نموذج جديد للوكلاء البرمجيين في الشرق الأوسط', story_kind: 'recurring_theme', status: 'merged', last_seen_at: '2027-01-01T00:00:00Z' }),
  story({ id: 'w-4', canonical_title: '智能眼镜 显示 模组 供应商 🚀🔥 Vision Pro 对比', story_kind: 'weird_new_kind', status: 'superseded', anchor_confidence: 1 }),
  story({ id: 'w-5', canonical_title: 'Jo', status: 'archived', post_count: 1, update_count: 1, last_seen_at: '2019-03-04T00:00:00Z' }),
  story({ id: 'w-6', canonical_title: '', canonical_summary: '', post_count: 2 }),
];

export const worstDetail: StoryDetail = storyDetail(worstStories[0], {
  anchor_post: { id: 'post-w', title: null, url: UNBREAKABLE_URL, platform: null, source_display_name: null, handle_or_url: '@northwind_industries_holdings_official_announcements', published_at: null },
  posts_by_role: {
    anchor: [{ story_id: 'w-1', post_id: 'post-w', role: 'anchor', post: post({ id: 'post-w', title: undefined, url: UNBREAKABLE_URL, source_display_name: undefined, source: '@northwind_industries_holdings_official_announcements', published_at: null }) }],
  },
  timeline: [
    update({ id: 'u-w1', update_date: null, title: 'إطلاق نموذج جديد 🚀 '.repeat(4), importance_score: undefined, summary: UNBREAKABLE_URL }),
    update({ id: 'u-w2', update_date: '2027-01-01', posts: [] }),
  ],
});

const hugeStories: StoryCard[] = Array.from({ length: 1000 }, (_, i) =>
  story({ id: `h-${i}`, canonical_title: `Story ${i + 1}: ${demoStories[i % 3].canonical_title}`, post_count: (i * 37) % 900, update_count: i % 7 }),
);

const STORY_SETS: Record<string, StoryCard[]> = {
  worst: worstStories,
  empty: [],
  one: [story({ post_count: 1, update_count: 1 })],
  huge: hugeStories,
};

/** The fixture API for `?data=<name>`: reads come from the fixtures. */
export function storiesFixtureApi(name: string): Partial<Api> | null {
  const list = STORY_SETS[name];
  if (!list) return null;
  const detailFor = (id: string) => {
    if (name === 'worst' && id === worstStories[0].id) return worstDetail;
    const card = list.find((s) => s.id === id);
    return card ? storyDetail(card) : null;
  };
  return {
    getStories: async () => ({ success: true, stories: list.slice(0, 100), total: list.length }),
    getStory: async (id: string) => ({ success: true, story: detailFor(id) }),
    getStoryTimeline: async (id: string) => ({ success: true, story_id: id, timeline: detailFor(id)?.timeline ?? [] }),
  };
}
