import { useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import * as Dialog from '@radix-ui/react-dialog';
import { Inbox, X } from 'lucide-react';

import type { UnreadCounts } from '../../services/api';
import { useReaderDirectory, useSourceDirectory } from '../../hooks/useReaderDirectory';
import { scopePath } from '../../lib/feedContext';
import { matchesSource, queryWords } from '../../lib/sourceSearch';
import { formatCount, middleTruncate } from '../../lib/format';
import { fieldClass, iconButtonClass } from '../ui/styles';
import { FOCUS_RING } from '../states';

const SOURCES_SHOWN = 12;

function Badge({ count }: { count: number | undefined }) {
  if (!count) return null;
  return (
    <>
      <span aria-hidden="true" className="ml-auto shrink-0 pl-2 text-[0.75rem] tabular-nums text-fg-3 group-aria-[current=page]:font-semibold group-aria-[current=page]:text-fg">
        {formatCount(count)}
      </span>
      <span className="sr-only">{`, ${formatCount(count)} unread`}</span>
    </>
  );
}

function RailLink({ to, current, label, count, icon, onNavigate }: {
  to: string; current: boolean; label: string; count?: number; icon?: ReactNode; onNavigate?: () => void;
}) {
  return (
    <Link
      to={to}
      onClick={onNavigate}
      aria-current={current ? 'page' : undefined}
      title={label}
      className={`group flex min-h-[2.25rem] items-center gap-2 rounded-md border px-2.5 text-[0.875rem] coarse:min-h-[2.75rem] ${current ? 'border-line-strong bg-surface font-semibold text-fg' : 'border-transparent text-fg-2 hover:bg-raised hover:text-fg'} ${FOCUS_RING}`}
    >
      {icon}
      <span className="min-w-0 truncate">{middleTruncate(label, 26)}</span>
      <Badge count={count} />
    </Link>
  );
}

function SectionTitle({ children }: { children: string }) {
  return <h2 className="px-2.5 pb-1.5 pt-6 text-[0.8125rem] lowercase text-fg-3">{children}</h2>;
}

/** The rail's source filter: placeholder only, a clear button while it has text, Esc clears. */
function SourceFilter({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="relative px-0.5 pb-1.5">
      <input
        ref={input}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && value) {
            event.preventDefault();
            onChange('');
          }
        }}
        aria-label="Filter sources"
        placeholder="filter sources"
        autoComplete="off"
        spellCheck={false}
        data-rail-filter=""
        className={`${fieldClass} h-8 pr-8 text-[0.8125rem] coarse:h-11 coarse:pr-11`}
      />
      {value ? (
        <button
          type="button"
          aria-label="Clear filter"
          onClick={() => {
            onChange('');
            input.current?.focus();
          }}
          className={`absolute inset-y-0 right-0.5 mb-1.5 flex w-8 items-center justify-center rounded-md text-fg-3 hover:text-fg coarse:w-11 ${FOCUS_RING}`}
        >
          <X aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}

function RailContent({ scope, counts, search, onNavigate }: {
  scope: string; counts: UnreadCounts | undefined; search: string; onNavigate?: () => void;
}) {
  const { folders } = useReaderDirectory();
  const [showAllSources, setShowAllSources] = useState(false);
  const [query, setQuery] = useState('');
  const words = useMemo(() => queryWords(query), [query]);
  const filtering = words.length > 0;
  const directory = useSourceDirectory(filtering);
  const withSearch = (path: string) => `${path}${search}`;
  const unread = (id: string) => counts?.by_source?.[id] ?? 0;

  // Most unread first, then by name. A source the directory cannot name (deleted)
  // has no row: "Unknown source 12,847" is noise; its posts stay in the main feed.
  const allSources = useMemo(() => [...directory.sources].sort((a, b) => (
    (counts?.by_source?.[b.id] ?? 0) - (counts?.by_source?.[a.id] ?? 0) || a.label.localeCompare(b.label)
  )), [directory.sources, counts]);
  const unreadSources = allSources.filter((source) => unread(source.id) > 0);
  const shownSources = filtering
    ? allSources.filter((source) => matchesSource(source, words))
    : showAllSources ? allSources : unreadSources.slice(0, SOURCES_SHOWN);
  const canExpand = allSources.length > Math.min(unreadSources.length, SOURCES_SHOWN);

  let emptyLine: string | null = null;
  if (!shownSources.length) {
    if (filtering) emptyLine = directory.isPending ? 'Loading…' : 'No source matches.';
    else emptyLine = counts && !directory.isPending ? 'Nothing unread.' : 'Loading…';
  }

  return (
    <nav aria-label="Feeds" className="flex min-h-0 flex-1 flex-col px-2 pb-4">
      <div className="space-y-0.5 pt-2">
        <RailLink
          to={withSearch('/')}
          current={scope === 'all'}
          label="Main feed"
          count={counts?.total}
          icon={<Inbox aria-hidden="true" className="h-4 w-4 shrink-0" />}
          onNavigate={onNavigate}
        />
      </div>

      <SectionTitle>Tracks</SectionTitle>
      {folders.isError ? (
        <p className="px-2.5 text-[0.8125rem] font-semibold text-fg">× Could not load tracks.</p>
      ) : folders.data?.length ? (
        <div className="space-y-0.5">
          {folders.data.map((folder) => {
            const folderScope = `folder:${folder.id}`;
            return (
              <RailLink
                key={folder.id}
                to={withSearch(scopePath(folderScope))}
                current={scope === folderScope}
                label={folder.name}
                count={counts?.by_folder?.[folder.id]}
                onNavigate={onNavigate}
              />
            );
          })}
        </div>
      ) : (
        <p className="px-2.5 text-[0.8125rem] text-fg-3">{folders.isPending ? 'Loading…' : 'No tracks yet.'}</p>
      )}

      <SectionTitle>{filtering || showAllSources ? 'Sources' : 'Sources with unread'}</SectionTitle>
      <SourceFilter value={query} onChange={setQuery} />
      <div className="space-y-0.5">
        {shownSources.map((source) => {
          const sourceScope = `source:${source.id}`;
          return (
            <RailLink
              key={source.id}
              to={withSearch(scopePath(sourceScope))}
              current={scope === sourceScope}
              label={source.label}
              count={unread(source.id)}
              onNavigate={onNavigate}
            />
          );
        })}
        {emptyLine ? <p className="px-2.5 py-1.5 text-[0.8125rem] text-fg-3">{emptyLine}</p> : null}
        {!filtering && canExpand ? (
          <button
            type="button"
            onClick={() => setShowAllSources((value) => !value)}
            className={`min-h-[2.25rem] w-full rounded-md px-2.5 text-left text-[0.8125rem] text-fg-2 underline decoration-fg-3/60 underline-offset-[0.22em] hover:text-fg hover:decoration-fg coarse:min-h-[2.75rem] ${FOCUS_RING}`}
          >
            {showAllSources ? 'Show fewer' : `Show all ${formatCount(allSources.length)} sources`}
          </button>
        ) : null}
      </div>

    </nav>
  );
}

/**
 * The reader's persistent nav (spec §F.1 item 8): the main feed, the tracks
 * and the sources with unread posts, each with its unread badge. The wordmark
 * and the app sections live in the top bar only; this rail is just the feeds.
 * The sources section has a filter over every source (not only those with
 * unread), and "Show all" expands the full list inline. At md and up it
 * is a sticky rail; below md the same content is a drawer opened from the
 * toolbar, which slides in from the left and leaves the same way.
 */
export default function ReaderNavRail({ scope, counts, search, drawerOpen, onDrawerOpenChange }: {
  scope: string;
  counts: UnreadCounts | undefined;
  /** The query string kept on rail links (view etc.), with its leading "?" or empty. */
  search: string;
  drawerOpen: boolean;
  onDrawerOpenChange: (open: boolean) => void;
}) {
  return (
    <>
      <aside className="reader-rail sticky top-topbar hidden h-[calc(100dvh-var(--topbar-h))] w-60 shrink-0 flex-col overflow-y-auto border-r border-line pt-2 md:flex lg:w-64">
        <RailContent scope={scope} counts={counts} search={search} />
      </aside>
      <Dialog.Root open={drawerOpen} onOpenChange={onDrawerOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="reader-drawer-overlay fixed inset-0 z-50 bg-black/50 md:hidden" />
          <Dialog.Content
            aria-describedby={undefined}
            // Esc in a non-empty source filter clears it (the field handles that); only
            // the next Esc closes the drawer.
            onEscapeKeyDown={(event) => {
              const target = event.target instanceof HTMLElement ? event.target : document.activeElement;
              if (target instanceof HTMLInputElement && target.matches('[data-rail-filter]') && target.value) event.preventDefault();
            }}
            className="reader-drawer reader-rail fixed inset-y-0 left-0 z-50 flex w-[min(18rem,85vw)] flex-col overflow-y-auto border-r border-line-strong bg-bg md:hidden"
          >
            <div className="flex items-center justify-between pl-4 pr-1 pt-1">
              <Dialog.Title className="text-[0.9375rem] font-semibold tracking-[-0.011em] text-fg">Feeds</Dialog.Title>
              <Dialog.Close
                aria-label="Close navigation"
                className={iconButtonClass}
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </Dialog.Close>
            </div>
            <RailContent scope={scope} counts={counts} search={search} onNavigate={() => onDrawerOpenChange(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
