/**
 * Feed fixtures (spec §F.7, break-ui CATALOG): the worst case, empty, one and a
 * huge feed. They are the regression data for FeedItem, FeedGroup and FeedList
 * and back the dev-only `?data=worst|empty|one|huge` switch on the reader.
 * Dates are relative to `now`, so "3h ago" and "in 2d" stay true whenever it renders.
 */
import type { FeedGroup, FeedGroupsPage, FeedItem, FeedPage, UnreadCounts } from '../../services/api';
import type { FeedFixture } from '../../hooks/useFeed';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export type FeedFixtureName = 'worst' | 'empty' | 'one' | 'huge';
export const FEED_FIXTURE_NAMES: readonly FeedFixtureName[] = ['worst', 'empty', 'one', 'huge'];

export function isFeedFixtureName(value: string | null | undefined): value is FeedFixtureName {
  return FEED_FIXTURE_NAMES.includes(value as FeedFixtureName);
}

function at(now: Date, offsetMs: number): string {
  return new Date(now.getTime() + offsetMs).toISOString();
}

function uuid(n: number): string {
  return `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
}

const SOURCE_SIMON = uuid(9001);

/** One item with sensible defaults (an unread blog post from three hours ago). */
export function feedItem(overrides: Partial<FeedItem> = {}, now: Date = new Date()): FeedItem {
  return {
    id: uuid(1),
    title: 'Prompt caching is now generally available',
    excerpt: 'Prompt caching lets you reuse a long prefix across requests, which cuts latency and cost for long documents.',
    url: 'https://simonwillison.net/2026/Oct/9/prompt-caching/',
    source_id: SOURCE_SIMON,
    source_display_name: 'Simon Willison’s Weblog',
    platform: 'rss',
    sort_at: at(now, -3 * HOUR),
    published_at: at(now, -3 * HOUR),
    read_at: null,
    starred_at: null,
    reading_minutes: 4,
    duration_seconds: null,
    media_thumb: null,
    ...overrides,
  };
}

export function feedPage(items: FeedItem[], next_cursor: string | null = null): FeedPage {
  return { success: true, items, next_cursor };
}

/** Every catalog row that applies to a feed row, spread across the first rows. */
export function worstFeedItems(now: Date = new Date()): FeedItem[] {
  return [
    feedItem({
      id: uuid(101),
      title: 'Why the new mixture-of-experts routing scheme that everybody is talking about this week does not actually reduce inference cost at the batch sizes most production deployments run, and what to measure instead before you migrate',
      source_display_name: 'https://export.arxiv.org/api/query?search_query=cat:cs.CL+AND+all:%22mixture%20of%20experts%22&sortBy=submittedDate',
      reading_minutes: 12_847,
      media_thumb: 'https://images.example.invalid/does-not-exist.png',
    }, now),
    feedItem({
      id: uuid(102),
      title: 'https://github.com/anthropics/claude-code/commit/dec92bc87ab6fe9c7be0fcba1f97966f902dd243?diff=split&w=1',
      excerpt: 'https://github.com/anthropics/claude-code/commit/dec92bc87ab6fe9c7be0fcba1f97966f902dd243?diff=split&w=1',
      platform: 'rss',
      source_display_name: 'https://github.com/anthropics/claude-code/commits/main.atom',
      reading_minutes: 1,
      read_at: at(now, -HOUR),
    }, now),
    feedItem({
      id: uuid(103),
      title: 'نموذج جديد للغة العربية يتفوق على النماذج السابقة في فهم اللهجات المحلية',
      excerpt: 'أعلن الباحثون اليوم عن نموذج لغوي جديد مدرب على مجموعة واسعة من النصوص العربية.',
      source_display_name: 'الجزيرة للتقنية',
      platform: 'telegram',
      starred_at: at(now, -2 * DAY),
      sort_at: at(now, 2 * DAY),
      published_at: at(now, 2 * DAY),
      reading_minutes: 0,
    }, now),
    feedItem({
      id: uuid(104),
      title: '日本語の大規模言語モデルの評価ベンチマークが公開されました🎉🚀',
      excerpt: '',
      source_display_name: '🤖 AI ニュース',
      platform: 'reddit',
      published_at: null,
      reading_minutes: null,
    }, now),
    feedItem({
      id: uuid(105),
      title: 'Jo',
      excerpt: 'x',
      source_display_name: 'J',
      platform: 'youtube',
      reading_minutes: null,
      duration_seconds: 4 * 3600 + 2 * 60 + 7,
      media_thumb: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="1200"><rect width="300" height="1200" fill="%234C8DFF"/></svg>',
      sort_at: at(now, -400 * DAY),
      published_at: at(now, -400 * DAY),
    }, now),
    feedItem({
      id: uuid(106),
      title: 'Ein außergewöhnlich langes zusammengesetztes Substantiv: Datenschutzgrundverordnungsdurchführungsbestimmungen',
      excerpt: 'Aleksandra Wiśniewska-Kowalczyk erklärt, warum <b>HTML</b> &amp; Markdown **nicht** gerendert werden dürfen.',
      source_display_name: 'Aleksandra Wiśniewska-Kowalczyk',
      duration_seconds: 0,
      platform: 'youtube',
      reading_minutes: null,
    }, now),
  ];
}

function group(items: FeedItem[], count: number): FeedGroup {
  const first = items[0];
  return {
    source_id: first.source_id,
    source_display_name: first.source_display_name,
    platform: first.platform,
    newest_sort_at: first.sort_at,
    count,
    items: items.slice(0, 3),
  };
}

function groupsPage(groups: FeedGroup[], next_cursor: string | null = null): FeedGroupsPage {
  return { success: true, groups, next_cursor };
}

function counts(total: number, bySource: Record<string, number> = {}): UnreadCounts {
  return { total, by_source: bySource, by_folder: {} };
}

export function feedFixture(name: FeedFixtureName, now: Date = new Date()): FeedFixture {
  if (name === 'empty') {
    return { name, stream: [feedPage([])], groups: [groupsPage([])], counts: counts(0) };
  }
  if (name === 'one') {
    const item = feedItem({ reading_minutes: 1 }, now);
    return {
      name,
      stream: [feedPage([item])],
      groups: [groupsPage([group([item], 1)])],
      counts: counts(1, { [item.source_id]: 1 }),
    };
  }
  if (name === 'huge') {
    // 1,000 items in pages of 30: proves pagination and the load-more path, with 12,847 unread.
    const items = Array.from({ length: 1000 }, (_, i) => feedItem({
      id: uuid(10_000 + i),
      title: `Daily arXiv digest item ${i + 1}: a perfectly ordinary paper title of ordinary length`,
      source_id: uuid(20_000 + (i % 40)),
      source_display_name: `arXiv cs.${['CL', 'LG', 'AI', 'CV'][i % 4]} feed ${i % 40}`,
      sort_at: at(now, -(i + 1) * 17 * MINUTE),
      published_at: at(now, -(i + 1) * 17 * MINUTE),
      read_at: i % 7 === 0 ? at(now, -MINUTE) : null,
    }, now));
    const pages: FeedPage[] = [];
    for (let i = 0; i < items.length; i += 30) pages.push(feedPage(items.slice(i, i + 30)));
    const bySource = new Map<string, FeedItem[]>();
    for (const item of items) bySource.set(item.source_id, [...(bySource.get(item.source_id) ?? []), item]);
    const groups = [...bySource.values()].map((list, i) => group(list, i === 0 ? 12_847 : list.length));
    return {
      name,
      stream: pages,
      groups: [groupsPage(groups.slice(0, 20)), groupsPage(groups.slice(20))],
      counts: counts(12_847),
    };
  }
  const items = worstFeedItems(now);
  const groups = [
    group(items.slice(0, 1), 12_847),
    group([items[1]], 1),
    group(items.slice(2, 5).map((item) => ({ ...item, source_id: items[2].source_id, source_display_name: items[2].source_display_name })), 0),
    group([items[5]], 2),
  ];
  return {
    name,
    stream: [feedPage(items)],
    groups: [groupsPage(groups)],
    counts: counts(12_847, { [items[0].source_id]: 12_847 }),
  };
}
