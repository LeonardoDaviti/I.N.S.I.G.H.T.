import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, RefreshCw } from 'lucide-react';
import { apiService } from '../services/api';
import type {
  MilestoneComparison,
  MilestoneEvidence,
  MilestoneLaneGroup,
  MilestoneListNode,
  MilestoneVendorGroup,
  MilestonesResponse,
} from '../services/api';
import { Button, Chip, Skeleton, StatusIcon } from './ui';
import { Notice } from './states';
import { formatCount, plural } from '../lib/format';
import { formatIssueShort } from '../lib/issueDate';
import { readableSourceName } from '../lib/briefingPage';
import { cn } from '../lib/utils';

/**
 * The milestones rail: the landmark releases reached inside one track's sources.
 *
 * Read-only. The tree is derived on read by the backend (no LLM, no stored nodes),
 * so this component only fetches and renders; lane editing lives elsewhere.
 *
 * `vite build` runs no tsc, so the API shape is never compile-checked. Every list
 * read goes through asArray().
 *
 * Mark IX: a plain timeline in the monochrome system. A vendor is a heading over a
 * hairline, a lane is a lowercase label, and a node's strength is its dot: filled
 * when several sources agree, a ring when only one source names it (shape, not hue).
 */

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

const FLAG_COPY: Record<string, string> = {
  single_source: '1 source',
  retrospective: 'retrospective',
  chain_start_at_corpus_edge: 'chain begins at corpus edge',
  named_by_briefing: 'named by briefing',
};

function Flag({ children }: { children: ReactNode }) {
  return <Chip variant="outline" className="font-normal text-fg-3">{children}</Chip>;
}

/** Four states, not `rows | null`. A failed lookup used to store [] and the
 *  "already loaded" guard then read that as done, so a drawer that lost one race
 *  rendered "Evidence (7)" over an empty box, unretryable, for the life of the page.
 *  'error' and 'loaded-but-empty' are different facts and must not paint the same. */
type EvidenceState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; rows: MilestoneEvidence[] }
  | { status: 'error'; message: string };

/** One node on a lane spine. The evidence drawer is the provenance affordance:
 *  the rail never asserts a landmark without the posts behind it one click away.
 *
 *  Evidence rows are NOT in the tree response any more - they were two thirds of a
 *  1.85MB payload for a drawer almost nobody opens - so opening the drawer fetches
 *  them. The count in the summary is node.post_count, which is by construction
 *  exactly the number of evidence rows the backend built the node from. */
function RailNode({ node, folderId }: { node: MilestoneListNode; folderId?: string }) {
  const dim = node.source_count <= 1;
  const comparisons = asArray<MilestoneComparison>(node.comparisons);
  const [evidence, setEvidence] = useState<EvidenceState>({ status: 'idle' });

  const loadEvidence = useCallback(async () => {
    // Only 'idle' and 'error' re-enter: 'loaded' is the cache, and holding off on
    // 'loading' stops an open/close/open flurry from firing a second request at a
    // route that rebuilds the whole tree (~6.6s) whenever the 60s memo has expired.
    if (evidence.status === 'loading' || evidence.status === 'loaded') return;
    setEvidence({ status: 'loading' });
    try {
      const res = await apiService.getMilestoneNode(node.node_key, folderId);
      // Every backend failure path — "Node not found" after a memo expiry rebuilt a
      // tree truncated at MAX_HIT_ROWS, a bridge exception, a non-2xx caught in the
      // service — comes back as success:false with an empty evidence list.
      if (!res?.success) {
        setEvidence({ status: 'error', message: res?.error || 'Failed to load evidence' });
        return;
      }
      setEvidence({ status: 'loaded', rows: asArray<MilestoneEvidence>(res.evidence) });
    } catch (e) {
      // getMilestoneNode already swallows its own errors; this is here so an
      // unexpected throw can never strand the drawer on "Loading…" forever.
      setEvidence({ status: 'error', message: e instanceof Error ? e.message : 'Failed to load evidence' });
    }
  }, [evidence.status, node.node_key, folderId]);

  const flags = asArray<string>(node.flags);
  const evidenceId = `evidence-${node.node_key}`;

  return (
    <li className="relative pb-4 last:pb-0">
      {/* The dot sits on the lane's spine (the ol's left border). Filled = corroborated
          by several sources; ring = one source only. */}
      <span
        aria-hidden="true"
        className={cn(
          'absolute -left-[1.3125rem] top-[0.4rem] h-[0.5625rem] w-[0.5625rem] rounded-full border-[1.5px] border-fg',
          dim ? 'bg-bg' : 'bg-fg',
        )}
      />
      <div className="min-w-0">
        <div className={cn('break-words leading-[1.35] [overflow-wrap:anywhere]', dim ? 'font-medium text-fg-2' : 'font-semibold text-fg')}>
          {node.custom_title || node.title}
        </div>
        <div className="mt-0.5 text-[0.8125rem] tabular-nums text-fg-3">
          <span className="whitespace-nowrap">{formatIssueShort(node.occurred_on)}</span>
          {' · '}
          <span className="whitespace-nowrap">{plural(node.source_count, 'source')}</span>
          {' · '}
          <span className="whitespace-nowrap">{plural(node.post_count, 'post')}</span>
        </div>

        {flags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {flags.map((flag) => (
              <Flag key={flag}>{FLAG_COPY[flag] || flag}</Flag>
            ))}
          </div>
        )}

        {comparisons.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {comparisons.slice(0, 3).map((c) => (
              <li key={`${c.node_key}-${c.post_id}`} className="min-w-0">
                <Link
                  to={`/posts/${c.post_id}`}
                  className="block truncate rounded-sm text-[0.8125rem] text-fg-2 hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
                  title={c.post_title}
                >
                  compared with <span className="font-medium text-fg">{c.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}

        {node.post_count > 0 && (
          <details
            className="group mt-1.5"
            // onToggle fires on close too; without the open check, collapsing a
            // drawer that failed would immediately re-request it in the background.
            onToggle={(e) => {
              if (e.currentTarget.open) void loadEvidence();
            }}
          >
            <summary
              aria-controls={evidenceId}
              className="inline-flex cursor-pointer list-none items-center gap-0.5 rounded-sm text-[0.8125rem] tabular-nums text-fg-3 hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg coarse:min-h-[2.75rem] [&::-webkit-details-marker]:hidden"
            >
              <ChevronRight aria-hidden="true" className="h-3.5 w-3.5 group-open:rotate-90" />
              evidence ({formatCount(node.post_count)})
            </summary>
            <div id={evidenceId} className="mt-1.5 space-y-2 border-l border-line pl-3">
              {evidence.status === 'loading' && (
                <div role="status" className="text-[0.8125rem] text-fg-3">Loading…</div>
              )}
              {evidence.status === 'error' && (
                <div role="alert" className="flex flex-wrap items-start gap-x-1.5 gap-y-1 text-[0.8125rem] text-fg">
                  <span className="mt-[0.2rem] inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm bg-inverse text-inverse-fg">
                    <StatusIcon status="failing" className="h-2 w-2" />
                    <span className="sr-only">Error:</span>
                  </span>
                  <span className="min-w-0 flex-1 break-words [overflow-wrap:anywhere]">{evidence.message}</span>
                  <button
                    type="button"
                    onClick={() => void loadEvidence()}
                    className="text-link rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
                  >
                    Retry
                  </button>
                </div>
              )}
              {/* post_count is meant to equal the row count, so zero rows here means
                  the two disagree — say so rather than paint an empty drawer. */}
              {evidence.status === 'loaded' && evidence.rows.length === 0 && (
                <div className="text-[0.8125rem] text-fg-3">No evidence rows returned.</div>
              )}
              {evidence.status === 'loaded' &&
                evidence.rows.map((e) => (
                  <Link
                    key={e.post_id}
                    to={`/posts/${e.post_id}`}
                    className="group/evidence block min-w-0 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
                  >
                    <div className="line-clamp-2 break-words text-[0.8125rem] leading-[1.4] text-fg-2 [overflow-wrap:anywhere] group-hover/evidence:text-fg">
                      {e.title || 'Untitled post'}
                    </div>
                    <div className="truncate text-[0.75rem] tabular-nums text-fg-3" title={`${e.role} · ${e.source_name}`}>
                      {e.role} · {readableSourceName(e.source_name)} · {formatIssueShort(e.published_at)}
                    </div>
                  </Link>
                ))}
            </div>
          </details>
        )}
      </div>
    </li>
  );
}

/** A lane spine: border-l + absolutely positioned dots. No SVG, no measurement. */
function Spine({ children, label }: { children: ReactNode; label: string }) {
  return (
    <ol aria-label={label} className="ml-1 list-none border-l border-line-strong pl-4">
      {children}
    </ol>
  );
}

function LaneBlock({ lane, folderId }: { lane: MilestoneLaneGroup; folderId?: string }) {
  const nodes = asArray<MilestoneListNode>(lane.nodes);
  return (
    <div>
      <div className="mb-2 flex min-w-0 items-center gap-1.5 text-[0.8125rem] lowercase text-fg-3">
        <span className="truncate" title={lane.lane_name}>{lane.lane_name}</span>
        {lane.node_count === 1 && <Flag>chain of 1</Flag>}
      </div>
      {/* Newest/highest version first — the backend orders by version_sort, not date. */}
      <Spine label={`${lane.lane_name} milestones`}>
        {nodes.map((node) => (
          <RailNode key={node.node_key} node={node} folderId={folderId} />
        ))}
      </Spine>
    </div>
  );
}

function VendorBlock({ vendor, folderId }: { vendor: MilestoneVendorGroup; folderId?: string }) {
  const lanes = asArray<MilestoneLaneGroup>(vendor.lanes);
  return (
    <section className="border-t border-line pt-4">
      <div className="mb-3 flex min-w-0 items-baseline justify-between gap-2">
        <h3 className="min-w-0 truncate font-semibold tracking-[-0.01em] text-fg" title={vendor.vendor}>
          {vendor.vendor}
        </h3>
        <span className="shrink-0 whitespace-nowrap text-[0.8125rem] tabular-nums text-fg-3">
          {plural(vendor.node_count, 'node')}
        </span>
      </div>
      <div className="space-y-5">
        {lanes.map((lane) => (
          <LaneBlock key={lane.lane_id} lane={lane} folderId={folderId} />
        ))}
      </div>
    </section>
  );
}

export default function MilestonesRail({
  folderId,
  className = '',
}: {
  folderId: string;
  className?: string;
}) {
  const [tree, setTree] = useState<MilestonesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    // No scope means nothing to derive; never leave the rail stuck on a skeleton.
    if (!folderId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    const res = await apiService.getMilestones({ folderId });
    if (!res?.success) setError(res?.error || 'Failed to load milestones');
    setTree(res ?? null);
    setLoading(false);
  }, [folderId]);

  useEffect(() => {
    void load();
  }, [load]);

  const vendors = asArray<MilestoneVendorGroup>(tree?.vendors);
  const papers = asArray<MilestoneListNode>(tree?.papers);
  const coverage = tree?.coverage;
  const stats = tree?.stats;
  const diagnostics = tree?.diagnostics;
  const hasAnything = vendors.length > 0 || papers.length > 0;

  return (
    <aside aria-labelledby="milestones-title" className={cn('min-w-0', className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="milestones-title" className="text-[1.0625rem] font-semibold tracking-[-0.01em] text-fg">
            Milestones
          </h2>
          <p className="mt-0.5 text-[0.8125rem] tabular-nums text-fg-2">
            {stats
              ? `${formatCount(stats.nodes)} reached · ${plural(stats.lanes, 'product line')}`
              : 'Landmark releases reached inside this track.'}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => void load()}
          disabled={loading}
          aria-label="Refresh milestones"
          title="Refresh milestones"
        >
          <RefreshCw aria-hidden="true" />
        </Button>
      </div>

      {error && (
        <Notice
          tone="error"
          title="Milestones did not load"
          message={error}
          action={{ label: 'Retry', onClick: () => void load() }}
          className="mt-4"
        />
      )}

      {loading && !tree && (
        <div role="status" aria-busy="true" className="mt-5 space-y-4">
          <span className="sr-only">Loading milestones</span>
          {[0, 1, 2].map((i) => (
            <div key={i} className="space-y-2 border-t border-line pt-4">
              <Skeleton className="h-3 w-1/2" />
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ))}
        </div>
      )}

      {!loading && !error && !hasAnything && (
        <div className="mt-4 rounded-md border border-dashed border-line-strong px-3 py-3 text-[0.8125rem] leading-[1.55] text-fg-2">
          {(coverage?.posts_in_scope ?? 0) === 0 ? (
            <>
              This track has {plural(tree?.scope?.source_count ?? coverage?.sources_in_scope ?? 0, 'source')} and no
              posts yet. Milestones reads posts; it fetches nothing itself, so this fills in after the next ingestion
              cycle.
            </>
          ) : (
            <>
              No landmark releases found in {plural(coverage?.posts_in_scope ?? 0, 'post')} yet. A milestone is a
              product line plus a version number; none of the{' '}
              {plural(diagnostics?.lanes_configured ?? 0, 'configured product line')} matched this track's posts. This
              fills in on its own as releases are announced.
            </>
          )}
        </div>
      )}

      {/* The `!loading` gate is load-bearing beyond the skeleton: it unmounts every
          RailNode for the duration of a refresh, which is what discards each drawer's
          fetched evidence. RailNode is keyed by node_key at a stable position, so if
          this ever renders the previous tree while the new one loads (the obvious
          anti-flicker "improvement"), React keeps those instances and a reopened
          drawer shows pre-refresh rows under a post-refresh count. Fold a per-load
          generation counter into the RailNode key before making that change. */}
      {!loading && vendors.length > 0 && (
        <div className="mt-5 space-y-6">
          {vendors.map((vendor) => (
            <VendorBlock key={vendor.vendor} vendor={vendor} folderId={folderId} />
          ))}
        </div>
      )}

      {!loading && papers.length > 0 && (
        <section className="mt-6 border-t border-line pt-4">
          <h3 className="mb-3 font-semibold tracking-[-0.01em] text-fg">Papers named by briefings</h3>
          <Spine label="Papers named by briefings">
            {papers.map((node) => (
              <RailNode key={node.node_key} node={node} folderId={folderId} />
            ))}
          </Spine>
        </section>
      )}

      {tree?.success && diagnostics && (
        <p className="mt-6 border-t border-line pt-3 text-[0.75rem] leading-[1.5] tabular-nums text-fg-3">
          Derived on read{tree.elapsed_ms != null ? ` in ${formatCount(tree.elapsed_ms)}ms` : ''} ·{' '}
          {diagnostics.lanes_matched}/{diagnostics.lanes_configured} product lines matched ·{' '}
          {plural(coverage?.weeks_covered ?? 0, 'week')} of history. No model runs here.
        </p>
      )}
    </aside>
  );
}
