import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import type { ArchiveCatalogEntry } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { formatRelativeTime } from '../../lib/dates';
import { formatCount, plural } from '../../lib/format';
import { sourceLabel } from '../../lib/sourceLabel';
import { Input, StatusGlyph, type Status } from '../ui';
import ArchiveSection, { ARCHIVE_CATALOG_KEY } from './ArchiveSection';

const sectionTitle = 'text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg';

/** Archive status -> glyph + word: archived is full, partial is half, nothing is a ring. */
function archiveGlyph(status?: string | null): { status: Status; label: string } {
  if (status === 'archived') return { status: 'ok', label: 'archived' };
  if (status === 'partial') return { status: 'due', label: 'partial' };
  return { status: 'scheduled', label: 'not archived' };
}

/** "youtube · 120 of 1,722 stored · 1,602 older posts not archived · measured 3d ago · checkpoint saved". */
function entryLine(entry: ArchiveCatalogEntry, now: Date): string {
  const stored = formatCount(entry.stored_posts ?? 0);
  const parts = [
    entry.platform,
    typeof entry.available_posts === 'number' ? `${stored} of ${formatCount(entry.available_posts)} stored` : `${stored} stored`,
  ];
  if (typeof entry.backlog_posts === 'number') {
    parts.push(entry.backlog_posts === 0 ? 'nothing older to archive' : `${plural(entry.backlog_posts, 'older post')} not archived`);
  }
  parts.push(entry.last_inspected_at ? `measured ${formatRelativeTime(entry.last_inspected_at, now)}` : 'not measured yet');
  if (entry.resume_ready) parts.push('checkpoint saved');
  return parts.join(' · ');
}

/**
 * Sources → ingestion → archive: every enabled source with what it stores, what
 * it has and how many older posts are not archived; the one picked (`?source=`) gets the sheet's archive
 * controls plus the pacing a long backfill needs.
 */
export default function IngestionArchive() {
  const api = useApi();
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState('');
  const catalog = useQuery({
    queryKey: [...ARCHIVE_CATALOG_KEY],
    queryFn: async () => {
      const response = await api.getArchiveCatalog();
      return response.sources ?? [];
    },
    staleTime: 30_000,
  });
  const entries = useMemo(() => catalog.data ?? [], [catalog.data]);

  const term = query.trim().toLowerCase();
  const shown = useMemo(() => (term
    ? entries.filter((entry) => [entry.display_name, entry.platform, entry.kind, entry.source_id]
      .some((value) => (value ?? '').toLowerCase().includes(term)))
    : entries), [entries, term]);
  const backlog = entries.reduce((sum, entry) => sum + (entry.backlog_posts ?? 0), 0);

  const selectedId = searchParams.get('source');
  const selected = entries.find((entry) => entry.source_id === selectedId) ?? null;
  const select = (id: string) => {
    const params = new URLSearchParams(searchParams);
    params.set('source', id);
    setSearchParams(params, { replace: true });
  };

  const now = new Date();
  const meta = catalog.isPending
    ? 'Loading…'
    : [plural(entries.length, 'source'), backlog ? `${plural(backlog, 'older post')} not archived` : null].filter(Boolean).join(' · ');

  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <section aria-labelledby="archive-catalog" className="min-w-0 space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="archive-catalog" className={sectionTitle}>Catalog</h2>
          <span className="text-[0.75rem] tabular-nums text-fg-3">{meta}</span>
        </div>
        {entries.length ? (
          <Input
            type="search"
            aria-label="Search the catalog"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search sources"
          />
        ) : null}
        {catalog.isError ? (
          <p className="text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]">Could not load the catalog: {catalog.error.message}</p>
        ) : (
          <ul className="max-h-[36rem] divide-y divide-line overflow-y-auto border-y border-line">
            {shown.map((entry) => {
              // The id only when there is no name at all: it is never a URL, so it would win over a derived one.
              const name = sourceLabel(entry.display_name || entry.source_id);
              const glyph = archiveGlyph(entry.archive_status);
              const isSelected = entry.source_id === selectedId;
              return (
                <li key={entry.source_id}>
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => select(entry.source_id)}
                    className={`w-full min-w-0 px-2 py-2 text-left text-[0.8125rem] transition-colors duration-[120ms] hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg motion-reduce:transition-none ${isSelected ? 'bg-raised' : ''}`}
                  >
                    <div className="flex min-w-0 items-center justify-between gap-3">
                      <span className="min-w-0 truncate font-medium text-fg" title={entry.display_name || undefined}>{name}</span>
                      <StatusGlyph status={glyph.status} label={glyph.label} className="shrink-0" />
                    </div>
                    <p className="mt-0.5 truncate text-[0.75rem] tabular-nums text-fg-3">{entryLine(entry, now)}</p>
                  </button>
                </li>
              );
            })}
            {!shown.length && !catalog.isPending ? (
              <li className="px-2 py-8 text-center text-[0.8125rem] text-fg-3">
                {entries.length ? `Nothing matches “${query}”.` : 'No enabled sources to archive.'}
              </li>
            ) : null}
          </ul>
        )}
      </section>
      <section aria-labelledby="archive-backfill" className="min-w-0 space-y-4">
        <h2 id="archive-backfill" className={sectionTitle}>{selected ? sourceLabel(selected.display_name || selected.source_id) : 'Backfill'}</h2>
        {selected ? <ArchiveSection key={selected.source_id} sourceId={selected.source_id} pacing /> : (
          <p className="text-[0.8125rem] text-fg-3">
            {catalog.isPending ? 'Loading…' : 'Choose a source to plan its backfill: where it continues from, how fast, and whether to resume the last run.'}
          </p>
        )}
      </section>
    </div>
  );
}
