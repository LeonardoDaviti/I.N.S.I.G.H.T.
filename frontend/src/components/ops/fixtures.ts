/**
 * Fixtures for the ops components (spec §F.7, break-ui CATALOG): a realistic
 * demo, the worst case, empty, one, and a huge list. They are the regression
 * data for SourceHealthTable and RunReportSummary and back the dev-only
 * `?data=worst|empty|one|huge` switch on Settings → Sources → Health.
 * Dates are relative to `now`, so "retry in 3h" stays true whenever it renders.
 */
import type { RunReport, SourceHealthRow, SourcesHealthResponse } from '../../services/api';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export type HealthFixtureName = 'worst' | 'empty' | 'one' | 'huge';
export const HEALTH_FIXTURE_NAMES: readonly HealthFixtureName[] = ['worst', 'empty', 'one', 'huge'];

export function isHealthFixtureName(value: string | null | undefined): value is HealthFixtureName {
  return HEALTH_FIXTURE_NAMES.includes(value as HealthFixtureName);
}

function at(now: Date, offsetMs: number): string {
  return new Date(now.getTime() + offsetMs).toISOString();
}

/** One row with sensible defaults (a healthy medium-cadence RSS feed, scheduled in 3h). */
export function healthRow(overrides: Partial<SourceHealthRow> = {}, now: Date = new Date()): SourceHealthRow {
  return {
    source_id: '00000000-0000-4000-8000-000000000001',
    display_name: 'Simon Willison’s Weblog',
    platform: 'rss',
    kind: 'generic_rss',
    enabled: true,
    in_main_digest: true,
    folders: [{ id: 'f-ai', name: 'AI engineering' }],
    stored_posts: 412,
    backlog_posts: null,
    tier: 'medium',
    mean_gap_hours: 19.5,
    interval_hours: 12,
    interval_basis: 'tier',
    override_hours: null,
    next_due_at: at(now, 3 * HOUR + 5 * MINUTE),
    would_fetch_now: false,
    decision: 'skip_not_due',
    decision_detail: null,
    status: 'deferred',
    last_attempt_at: at(now, -9 * HOUR),
    last_success_at: at(now, -9 * HOUR),
    last_outcome: 'healthy',
    last_fetched_posts: 4,
    last_error: null,
    last_error_at: null,
    consecutive_failures: 0,
    next_retry_at: null,
    dormant: false,
    ...overrides,
  };
}

function summarize(rows: SourceHealthRow[]): SourcesHealthResponse['summary'] {
  const summary = { due_now: 0, deferred: 0, backoff: 0, unavailable: 0, errors: 0 };
  for (const row of rows) {
    if (row.status === 'due') summary.due_now += 1;
    else if (row.status === 'deferred') summary.deferred += 1;
    else if (row.status === 'backoff') summary.backoff += 1;
    else if (row.status === 'unavailable') summary.unavailable += 1;
    else if (row.status === 'error') summary.errors += 1;
  }
  return summary;
}

export function healthResponse(rows: SourceHealthRow[], now: Date = new Date()): SourcesHealthResponse {
  return { success: true, generated_at: now.toISOString(), rows, summary: summarize(rows) };
}

const LONG_ERROR = 'HTTPSConnectionPool(host=\'tg.i-c-a.su\', port=443): Max retries exceeded with url: '
  + '/rss/ai_newz_channel_with_a_very_long_handle_name?limit=50&format=atom&nocache=1696850000000 '
  + '(Caused by NewConnectionError(\'<urllib3.connection.HTTPSConnection object at 0x7f3a9c2b1d90>: '
  + 'Failed to establish a new connection: [Errno -3] Temporary failure in name resolution\'))';

/** Every failure from the break-ui catalog, spread across rows like real data. */
export function worstHealthRows(now: Date = new Date()): SourceHealthRow[] {
  return [
    healthRow({
      source_id: 'w-backoff-dormant',
      display_name: 'Bundesministerium für Wirtschaftsförderungsangelegenheiten und Digitalisierungsstrategie — Pressemitteilungen',
      platform: 'rss',
      status: 'backoff',
      decision: 'skip_backoff',
      consecutive_failures: 9,
      dormant: true,
      next_retry_at: at(now, 5 * DAY + HOUR),
      next_due_at: at(now, 5 * DAY + HOUR),
      last_outcome: 'error',
      last_error: LONG_ERROR,
      last_error_at: at(now, -2 * DAY),
      last_success_at: at(now, -46 * DAY),
      stored_posts: 12847,
      folders: [
        { id: 'f1', name: 'Policy & regulation (EU, DE, FR, NL, PL, CZ)' },
        { id: 'f2', name: 'Industrial strategy' },
        { id: 'f3', name: 'Reading list — someday' },
      ],
    }, now),
    healthRow({
      source_id: 'w-unbreakable-url',
      display_name: 'https://export.arxiv.org/api/query?search_query=cat:physics.optics+OR+cat:cs.CV&sortBy=submittedDate&sortOrder=descending&max_results=200',
      kind: 'generic_rss',
      status: 'error',
      decision: 'fetch_retry',
      would_fetch_now: true,
      consecutive_failures: 1,
      next_retry_at: at(now, -10 * MINUTE),
      next_due_at: at(now, -10 * MINUTE),
      last_outcome: 'error',
      last_error: 'HTTP 503',
      last_error_at: at(now, -HOUR),
      in_main_digest: false,
      folders: [],
    }, now),
    healthRow({
      source_id: 'w-telegram-unavailable',
      display_name: 'ai_newz',
      platform: 'telegram',
      kind: 'telegram_mtproto',
      status: 'unavailable',
      decision: 'skip_unavailable',
      decision_detail: 'No Telegram session: run `python -m insight_core.scripts.telegram_login` on the server',
      tier: 'unknown',
      mean_gap_hours: null,
      interval_hours: 24,
      interval_basis: 'probation',
      stored_posts: 0,
      last_attempt_at: null,
      last_success_at: null,
      last_outcome: null,
      last_fetched_posts: null,
      next_due_at: null,
    }, now),
    healthRow({
      source_id: 'w-rtl',
      display_name: 'الجزيرة نت — أخبار التكنولوجيا والذكاء الاصطناعي',
      tier: 'fast',
      mean_gap_hours: 0.4,
      interval_hours: 1,
      interval_basis: 'profile_floor',
      status: 'due',
      decision: 'fetch_due',
      would_fetch_now: true,
      next_due_at: at(now, -3 * DAY),
      last_fetched_posts: 50,
      backlog_posts: 0,
    }, now),
    healthRow({
      source_id: 'w-new',
      display_name: '🚀🤖 r/LocalLLaMA 🦙',
      platform: 'reddit',
      kind: 'generic_rss',
      status: 'due',
      decision: 'fetch_new_source',
      would_fetch_now: true,
      tier: 'unknown',
      interval_basis: 'probation',
      interval_hours: 24,
      mean_gap_hours: null,
      next_due_at: null,
      last_attempt_at: null,
      last_success_at: null,
      last_outcome: null,
      last_fetched_posts: null,
      stored_posts: 1,
    }, now),
    healthRow({
      source_id: 'w-override-cjk',
      display_name: '日本経済新聞 テクノロジー',
      override_hours: 2160,
      interval_hours: 2160,
      interval_basis: 'override',
      tier: 'slow',
      mean_gap_hours: 1100,
      next_due_at: at(now, 89 * DAY),
      last_outcome: 'empty',
      last_fetched_posts: 0,
      backlog_posts: 12847,
    }, now),
    healthRow({
      source_id: 'w-yt-guard',
      display_name: 'Two Minute Papers',
      platform: 'youtube',
      kind: 'youtube_channel',
      tier: 'medium',
      interval_basis: 'backlog_guard',
      interval_hours: 0.5,
      next_due_at: at(now, 20 * MINUTE),
    }, now),
    healthRow({
      source_id: 'w-disabled',
      display_name: 'Jo',
      enabled: false,
      status: 'disabled',
      decision: 'skip_disabled',
      would_fetch_now: false,
      next_due_at: null,
      decision_detail: 'Source is disabled',
      last_success_at: at(now, 400 * DAY),
    }, now),
  ];
}

export function healthFixture(name: HealthFixtureName, now: Date = new Date()): SourcesHealthResponse {
  switch (name) {
    case 'empty':
      return healthResponse([], now);
    case 'one':
      return healthResponse([healthRow({ stored_posts: 1, last_fetched_posts: 1 }, now)], now);
    case 'huge':
      return healthResponse(
        Array.from({ length: 1000 }, (_, index) => {
          const pick = worstHealthRows(now)[index % 8];
          return { ...pick, source_id: `${pick.source_id}-${index}`, display_name: `${pick.display_name} #${index + 1}` };
        }),
        now,
      );
    default:
      return healthResponse(worstHealthRows(now), now);
  }
}

export function runReport(overrides: Partial<RunReport> = {}): RunReport {
  return {
    run_id: 'job-1',
    trigger: 'manual',
    selector: { kind: 'all' },
    force: false,
    status: 'success',
    summary: '12 due, 66 deferred, 0 failed; 48 new posts',
    started_at: '2026-10-09T10:00:00+00:00',
    finished_at: '2026-10-09T10:01:05+00:00',
    duration_s: 65.2,
    sources_considered: 78,
    sources_fetched: 12,
    sources_failed: 0,
    decisions: { fetch_due: 12, skip_not_due: 63, skip_unavailable: 3 },
    posts_fetched: 240,
    posts_inserted: 48,
    posts_updated: 9,
    posts_failed: 0,
    failures: [],
    post_failures: [],
    inserted_by_source: [
      { source_id: 's1', display_name: 'Simon Willison’s Weblog', inserted: 30 },
      { source_id: 's2', display_name: 'Two Minute Papers', inserted: 18 },
    ],
    enrichment: { entity: { posts: 48, chunks: 1, failed_chunks: 0 }, event: { posts: 48, chunks: 1, failed_chunks: 0 } },
    ...overrides,
  };
}

/** A partial run with the long, the RTL and the unbreakable values in its lists. */
export function worstRunReport(): RunReport {
  return runReport({
    status: 'partial',
    force: true,
    sources_considered: 12847,
    sources_fetched: 12847,
    sources_failed: 3,
    decisions: { fetch_forced: 12847 },
    posts_inserted: 1,
    posts_updated: 0,
    posts_failed: 2,
    failures: [
      { source_id: 'a', display_name: 'Bundesministerium für Wirtschaftsförderungsangelegenheiten und Digitalisierungsstrategie', stage: 'fetch', error: LONG_ERROR },
      { source_id: 'b', display_name: 'الجزيرة نت — أخبار التكنولوجيا', stage: 'save', error: 'deadlock detected' },
      { source_id: 'c', display_name: '🚀🤖 r/LocalLLaMA 🦙', stage: 'connector', error: '' },
    ],
    post_failures: [
      { url: 'https://example.com/a/very/long/path/that/never/breaks/'.repeat(4), source_id: 'a', stage: 'upsert', error: 'value too long for type character varying(2048)' },
      { url: null, source_id: 'b', stage: 'discarded', error: 'no url' },
    ],
    inserted_by_source: [{ source_id: 'b', display_name: 'الجزيرة نت — أخبار التكنولوجيا', inserted: 1 }],
    enrichment: null,
  });
}
