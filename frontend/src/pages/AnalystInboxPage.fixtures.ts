import type { Api, InboxAction, InboxBatch, InboxItem, SourceWithSettings } from '../services/api';

/**
 * Inbox fixtures (break-ui, spec §F.7). `worst` spreads long, missing, RTL/CJK/emoji
 * and unbreakable values, unknown statuses and extreme scores over the first rows.
 */

export const INBOX_FIXTURE_NAMES = ['worst', 'empty', 'one', 'huge'] as const;

const UNBREAKABLE_URL =
  'https://northwind-industries-holdings.example.com/press/2026/10/09/announcing-the-general-availability-of-the-agent-orchestration-runtime-v2.html';

export function batch(overrides: Partial<InboxBatch> = {}): InboxBatch {
  return {
    id: 'batch-1',
    scope_type: 'daily',
    scope_value: null,
    generated_for_date: '2026-10-09',
    status: 'ready',
    item_count: 24,
    pending_count: 18,
    acted_count: 6,
    ...overrides,
  };
}

export function item(overrides: Partial<InboxItem> = {}): InboxItem {
  return {
    id: 'item-1',
    batch_id: 'batch-1',
    batch_scope_type: 'daily',
    batch_generated_for_date: '2026-10-09',
    target_type: 'post',
    target_id: 'post-1',
    status: 'pending',
    priority_score: 7.4,
    novelty_score: 0.81,
    evidence_score: 0.6,
    duplication_penalty: 0.05,
    source_priority_score: 0.7,
    reason_summary: 'New announcement from a high-priority source with two corroborating posts.',
    reasons: [
      { code: 'novel', label: 'Novel', detail: 'No earlier post covers this', weight: 0.4 },
      { code: 'corroborated', label: 'Corroborated', detail: '2 other sources', weight: 0.3 },
    ],
    surfaced_at: '2026-10-09T07:40:00Z',
    target_preview: { id: 'post-1', title: 'Anthropic ships Claude Code skills', source_display_name: 'Simon Willison', platform: 'rss', url: 'https://simonwillison.net/2026/Oct/9/skills/' },
    ...overrides,
  };
}

export const demoBatches: InboxBatch[] = [batch(), batch({ id: 'batch-2', generated_for_date: '2026-10-08', item_count: 31, pending_count: 0, acted_count: 31, status: 'done' })];

export const worstBatches: InboxBatch[] = [
  batch({ id: 'wb-1', scope_type: 'vertical_agentic_news_and_harness_engineering_weekly', scope_value: 'f8571844-1065-4d96-85b5-1dfd9dc7b111', item_count: 12847, pending_count: 12847, acted_count: 0 }),
  batch({ id: 'wb-2', scope_type: 'daily', generated_for_date: null, item_count: 1, pending_count: 1, acted_count: 0, status: undefined }),
  batch({ id: 'wb-3', scope_type: 'source', generated_for_date: '2027-01-01', item_count: 0, pending_count: 0, acted_count: 0, status: 'weird_status' }),
];

export const worstItems: InboxItem[] = [
  item({
    id: 'wi-1',
    batch_id: 'wb-1',
    priority_score: 12847.123456,
    reason_summary:
      'A very long reason summary that the ranker produced by concatenating every reason detail without punctuation because nobody capped it and it keeps going for a while longer than anyone expected it to',
    reasons: [
      { code: 'a', label: 'Source priority', detail: UNBREAKABLE_URL, weight: 1 },
      { code: 'b', label: 'Novel', detail: '', weight: 0 },
      { code: 'c', label: 'Corroborated', detail: 'by 12,847 posts' },
      { code: 'd', label: 'Hidden fourth reason', detail: 'never shown in the list row' },
    ],
    target_preview: { id: 'post-w1', title: UNBREAKABLE_URL, source_display_name: '@northwind_industries_holdings_official_announcements', platform: 'telegram', url: UNBREAKABLE_URL },
  }),
  item({ id: 'wi-2', batch_id: 'wb-1', target_type: 'story', status: 'accepted', target_preview: { id: 'story-2', canonical_title: 'إطلاق نموذج جديد للوكلاء البرمجيين في الشرق الأوسط', story_kind: 'recurring_theme', status: 'active', anchor_post: { id: 'post-a' } }, surfaced_at: '2027-01-01T00:00:00Z' }),
  item({ id: 'wi-3', batch_id: 'wb-1', status: 'rejected_noise', target_preview: { title: '智能眼镜 显示 模组 供应商 🚀🔥', platform: 'reddit' }, novelty_score: undefined, evidence_score: undefined, duplication_penalty: undefined, reasons: [], reason_summary: null }),
  item({ id: 'wi-4', batch_id: 'wb-1', status: 'blocked_source', target_preview: null, surfaced_at: null, priority_score: undefined }),
  item({ id: 'wi-5', batch_id: 'wb-1', status: 'snoozed', target_type: 'cluster', target_preview: { title: 'Jo' } }),
  item({ id: 'wi-6', batch_id: 'wb-1', status: 'saved', target_preview: { title: '' } }),
];

const worstActions: InboxAction[] = [
  { id: 'a-1', target_type: 'post', target_id: 'post-w1', action_type: 'snooze', actor_id: 'aleksandra.wisniewska-kowalczyk@northwind-industries-holdings.example.com', created_at: '2026-10-09T09:00:00Z', payload: { until: '2026-10-10', note: UNBREAKABLE_URL } },
  { id: 'a-2', target_type: 'post', target_id: 'post-w1', action_type: 'accept', created_at: null },
];

const worstSources: SourceWithSettings[] = [
  { id: 'src-1', platform: 'rss', handle_or_url: UNBREAKABLE_URL, enabled: true, post_count: 12847, settings: {} as SourceWithSettings['settings'] },
];

const SETS: Record<string, { batches: InboxBatch[]; items: InboxItem[] }> = {
  worst: { batches: worstBatches, items: worstItems },
  empty: { batches: [], items: [] },
  one: { batches: [batch({ item_count: 1, pending_count: 1, acted_count: 0 })], items: [item()] },
  huge: {
    batches: Array.from({ length: 50 }, (_, i) => batch({ id: `hb-${i}`, generated_for_date: `2026-${String(9 - Math.floor(i / 28)).padStart(2, '0')}-${String(28 - (i % 28)).padStart(2, '0')}` })),
    items: Array.from({ length: 200 }, (_, i) => item({ id: `hi-${i}`, batch_id: 'hb-0', priority_score: 10 - i / 20, target_preview: { id: `p-${i}`, title: `Candidate ${i + 1}: Anthropic ships Claude Code skills`, source_display_name: 'Simon Willison', platform: 'rss' } })),
  },
};

/** The fixture API for `?data=<name>`: reads from the fixtures, writes are no-ops. */
export function inboxFixtureApi(name: string): Partial<Api> | null {
  const set = SETS[name];
  if (!set) return null;
  const find = (id: string) => set.items.find((i) => i.id === id) || null;
  return {
    getSourcesWithSettings: async () => ({ success: true, sources: name === 'worst' ? worstSources : [] }) as Awaited<ReturnType<Api['getSourcesWithSettings']>>,
    getInboxBatches: async () => ({ success: true, batches: set.batches, total: set.batches.length }),
    getInbox: async (batchId?: string) => ({ success: true, batch: set.batches.find((b) => b.id === batchId) || null, items: set.items }),
    getInboxItems: async (filters) => ({ success: true, items: set.items.slice(0, filters?.limit ?? 25), total: set.items.length }),
    getInboxItem: async (id: string) => ({ success: true, item: find(id), target: find(id)?.target_preview ?? null, actions: [] }),
    getInboxActions: async () => ({ success: true, actions: name === 'worst' ? worstActions : [] }),
    recordInboxAction: async (id: string) => ({ success: true, item: find(id), side_effects: [] }),
    rebuildInbox: async () => ({ success: true }),
  };
}
