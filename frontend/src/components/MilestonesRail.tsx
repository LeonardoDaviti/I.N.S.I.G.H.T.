import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, FileText, GitBranch, RefreshCw } from 'lucide-react';
import { apiService } from '../services/api';
import type {
  MilestoneLaneGroup,
  MilestoneNode,
  MilestoneVendorGroup,
  MilestonesResponse,
} from '../services/api';

/**
 * The milestones rail: the landmark releases reached inside one track's sources.
 *
 * Read-only. The tree is derived on read by the backend (no LLM, no stored nodes),
 * so this component only fetches and renders; lane editing lives elsewhere.
 *
 * `vite build` runs no tsc, so the API shape is never compile-checked. Every list
 * read goes through asArray().
 */

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function shortDate(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 10);
  return parsed.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
}

const FLAG_COPY: Record<string, string> = {
  single_source: '1 source',
  retrospective: 'retrospective',
  chain_start_at_corpus_edge: 'chain begins at corpus edge',
  named_by_briefing: 'named by briefing',
};

function Chip({ children, tone = 'muted' }: { children: ReactNode; tone?: 'muted' | 'faint' }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
        tone === 'faint' ? 'text-gray-400' : 'text-gray-500'
      }`}
    >
      {children}
    </span>
  );
}

/** One node on a lane spine. The evidence drawer is the provenance affordance:
 *  the rail never asserts a landmark without the posts behind it one click away. */
function RailNode({ node }: { node: MilestoneNode }) {
  const dim = node.source_count <= 1;
  const evidence = asArray<MilestoneNode['evidence'][number]>(node.evidence);
  const comparisons = asArray<MilestoneNode['comparisons'][number]>(node.comparisons);

  return (
    <div className="relative pb-3 last:pb-0">
      <span
        aria-hidden="true"
        className={`absolute top-1.5 h-2 w-2 rounded-full ring-2 ring-white ${
          dim ? 'bg-gray-300' : 'bg-indigo-500'
        }`}
        style={{ left: '-20.5px' }}
      />
      <div className={dim ? 'opacity-80' : ''}>
        <div className="text-sm font-semibold leading-snug text-gray-900">
          {node.custom_title || node.title}
        </div>
        <div className="mt-0.5 text-xs text-gray-500">
          {shortDate(node.occurred_on)} · {node.source_count}{' '}
          {node.source_count === 1 ? 'source' : 'sources'} · {node.post_count}{' '}
          {node.post_count === 1 ? 'post' : 'posts'}
        </div>

        {asArray<string>(node.flags).length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {asArray<string>(node.flags).map((flag) => (
              <Chip key={flag} tone="faint">
                {FLAG_COPY[flag] || flag}
              </Chip>
            ))}
          </div>
        )}

        {comparisons.length > 0 && (
          <div className="mt-1 space-y-0.5">
            {comparisons.slice(0, 3).map((c) => (
              <Link
                key={`${c.node_key}-${c.post_id}`}
                to={`/posts/${c.post_id}`}
                className="block truncate text-xs text-gray-500 hover:text-gray-800"
                title={c.post_title}
              >
                compared with <span className="font-medium">{c.title}</span>
              </Link>
            ))}
          </div>
        )}

        {evidence.length > 0 && (
          <details className="mt-1 group">
            <summary className="cursor-pointer list-none text-[11px] text-gray-400 hover:text-gray-600">
              <ChevronRight className="mr-0.5 inline h-3 w-3 transition group-open:rotate-90" />
              Evidence ({evidence.length})
            </summary>
            <div className="mt-1.5 space-y-1.5 border-l border-gray-200 pl-2">
              {evidence.map((e) => (
                <Link key={e.post_id} to={`/posts/${e.post_id}`} className="block hover:opacity-80">
                  <div className="line-clamp-2 text-[11px] leading-snug text-gray-700">{e.title}</div>
                  <div className="truncate text-[10px] uppercase tracking-wide text-gray-400">
                    {e.role} · {e.source_name} · {shortDate(e.published_at)}
                  </div>
                </Link>
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

function LaneBlock({ lane }: { lane: MilestoneLaneGroup }) {
  const nodes = asArray<MilestoneNode>(lane.nodes);
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-gray-400">
        <span className="truncate">{lane.lane_name}</span>
        {lane.node_count === 1 && <Chip tone="faint">chain of 1</Chip>}
      </div>
      {/* THE SPINE: border-l + absolutely positioned dots. No SVG, no measurement.
          Newest/highest version first — the backend orders by version_sort, not date. */}
      <div className="relative border-l border-gray-200 pl-4">
        {nodes.map((node) => (
          <RailNode key={node.node_key} node={node} />
        ))}
      </div>
    </div>
  );
}

function VendorBlock({ vendor }: { vendor: MilestoneVendorGroup }) {
  const lanes = asArray<MilestoneLaneGroup>(vendor.lanes);
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-3">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className="truncate text-sm font-semibold text-gray-900">{vendor.vendor}</div>
        <Chip tone="faint">
          {vendor.node_count} {vendor.node_count === 1 ? 'node' : 'nodes'}
        </Chip>
      </div>
      <div className="space-y-4">
        {lanes.map((lane) => (
          <LaneBlock key={lane.lane_id} lane={lane} />
        ))}
      </div>
    </div>
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
  const papers = asArray<MilestoneNode>(tree?.papers);
  const coverage = tree?.coverage;
  const stats = tree?.stats;
  const diagnostics = tree?.diagnostics;
  const hasAnything = vendors.length > 0 || papers.length > 0;

  return (
    <aside className={`rounded-xl border border-gray-200 bg-white p-4 ${className}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <GitBranch className="h-4 w-4 text-indigo-500" />
          <h2 className="text-sm font-semibold text-gray-900">Milestones</h2>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          aria-label="Refresh milestones"
          className="shrink-0 rounded-md border border-gray-200 bg-white p-1 text-gray-500 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <p className="mt-1 text-xs text-gray-500">
        {stats
          ? `${stats.nodes} reached · ${stats.lanes} product ${stats.lanes === 1 ? 'line' : 'lines'}`
          : 'Landmark releases reached inside this track.'}
      </p>

      {error && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          {error}
          <button onClick={() => void load()} className="ml-2 underline">
            Retry
          </button>
        </div>
      )}

      {loading && !tree && (
        <div className="mt-4 space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="animate-pulse rounded-lg border border-gray-200 bg-gray-50 p-3">
              <div className="h-3 w-1/2 rounded bg-gray-200" />
              <div className="mt-2 h-3 w-3/4 rounded bg-gray-100" />
              <div className="mt-1.5 h-3 w-2/3 rounded bg-gray-100" />
            </div>
          ))}
        </div>
      )}

      {!loading && !error && !hasAnything && (
        <div className="mt-4 rounded-lg border border-dashed border-gray-300 bg-gray-50 p-3 text-xs leading-relaxed text-gray-600">
          {(coverage?.posts_in_scope ?? 0) === 0 ? (
            <>
              This track has {tree?.scope?.source_count ?? coverage?.sources_in_scope ?? 0} sources
              and no posts yet. Milestones reads posts — it fetches nothing itself, so this fills in
              after the next ingestion cycle.
            </>
          ) : (
            <>
              No landmark releases found in {coverage?.posts_in_scope ?? 0} posts yet. A milestone is
              a product line plus a version number; none of the{' '}
              {diagnostics?.lanes_configured ?? 0} configured product lines matched this track's
              posts. This fills in on its own as releases are announced.
            </>
          )}
        </div>
      )}

      {!loading && vendors.length > 0 && (
        <div className="mt-4 space-y-3">
          {vendors.map((vendor) => (
            <VendorBlock key={vendor.vendor} vendor={vendor} />
          ))}
        </div>
      )}

      {!loading && papers.length > 0 && (
        <div className="mt-4">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-gray-400">
            <FileText className="h-3 w-3" />
            Papers named by briefings
          </div>
          <div className="relative border-l border-gray-200 pl-4">
            {papers.map((node) => (
              <RailNode key={node.node_key} node={node} />
            ))}
          </div>
        </div>
      )}

      {tree?.success && diagnostics && (
        <p className="mt-4 border-t border-gray-100 pt-2 text-[10px] leading-relaxed text-gray-400">
          Derived on read{tree.elapsed_ms != null ? ` in ${tree.elapsed_ms}ms` : ''} ·{' '}
          {diagnostics.lanes_matched}/{diagnostics.lanes_configured} product lines matched ·{' '}
          {coverage?.weeks_covered ?? 0} weeks of history. No model runs here.
        </p>
      )}
    </aside>
  );
}
