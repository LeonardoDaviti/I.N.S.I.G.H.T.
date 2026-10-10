import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import * as Dialog from '@radix-ui/react-dialog';
import { Inbox, Star, X } from 'lucide-react';

import type { FeedFilter, UnreadCounts } from '../../services/api';
import { useReaderDirectory } from '../../hooks/useReaderDirectory';
import { scopePath } from '../../lib/feedContext';
import { sourceLabel } from '../../lib/sourceLabel';
import { formatCount, middleTruncate } from '../../lib/format';
import { iconButtonClass } from '../ui/styles';
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

function RailContent({ scope, filter, counts, search, onNavigate }: {
  scope: string; filter: FeedFilter; counts: UnreadCounts | undefined; search: string; onNavigate?: () => void;
}) {
  const { folders, health, sourceNames } = useReaderDirectory();
  const [showAllSources, setShowAllSources] = useState(false);
  const withSearch = (path: string) => `${path}${search}`;

  const unreadSources = Object.entries(counts?.by_source ?? {})
    .filter(([, count]) => count > 0)
    // A source the directory cannot name (deleted, or not in the health rows) has no
    // useful row here: "Unknown source 12,847" is noise. Its posts stay in All posts.
    .filter(([sourceId]) => health.isPending || sourceNames.has(sourceId))
    .sort((a, b) => b[1] - a[1] || (sourceNames.get(a[0]) ?? '').localeCompare(sourceNames.get(b[0]) ?? ''));
  const shownSources = showAllSources ? unreadSources : unreadSources.slice(0, SOURCES_SHOWN);

  return (
    <nav aria-label="Feeds" className="flex min-h-0 flex-1 flex-col px-2 pb-4">
      <div className="space-y-0.5 pt-2">
        <RailLink
          to={withSearch('/')}
          current={scope === 'all' && filter !== 'starred'}
          label="All posts"
          count={counts?.total}
          icon={<Inbox aria-hidden="true" className="h-4 w-4 shrink-0" />}
          onNavigate={onNavigate}
        />
        <RailLink
          to="/?filter=starred"
          current={scope === 'all' && filter === 'starred'}
          label="Starred"
          icon={<Star aria-hidden="true" className="h-4 w-4 shrink-0" />}
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

      <SectionTitle>Sources with unread</SectionTitle>
      {unreadSources.length ? (
        <div className="space-y-0.5">
          {shownSources.map(([sourceId, count]) => {
            const sourceScope = `source:${sourceId}`;
            const raw = sourceNames.get(sourceId);
            const name = raw ? sourceLabel(raw) : 'Loading…';
            return (
              <RailLink
                key={sourceId}
                to={withSearch(scopePath(sourceScope))}
                current={scope === sourceScope}
                label={name}
                count={count}
                onNavigate={onNavigate}
              />
            );
          })}
          {unreadSources.length > SOURCES_SHOWN ? (
            <button
              type="button"
              onClick={() => setShowAllSources((value) => !value)}
              className={`min-h-[2.25rem] w-full rounded-md px-2.5 text-left text-[0.8125rem] text-fg-2 underline decoration-fg-3/60 underline-offset-[0.22em] hover:text-fg hover:decoration-fg coarse:min-h-[2.75rem] ${FOCUS_RING}`}
            >
              {showAllSources ? 'Show fewer' : `Show all ${formatCount(unreadSources.length)}`}
            </button>
          ) : null}
        </div>
      ) : (
        <p className="px-2.5 text-[0.8125rem] text-fg-3">{counts ? 'Nothing unread.' : 'Loading…'}</p>
      )}

    </nav>
  );
}

/**
 * The reader's persistent nav (spec §F.1 item 8): All posts, Starred, the tracks
 * and the sources with unread posts, each with its unread badge. The wordmark
 * and the app sections live in the top bar only; this rail is just the feeds. At md and up it
 * is a sticky rail; below md the same content is a drawer opened from the
 * toolbar, which slides in from the left and leaves the same way.
 */
export default function ReaderNavRail({ scope, filter, counts, search, drawerOpen, onDrawerOpenChange }: {
  scope: string;
  filter: FeedFilter;
  counts: UnreadCounts | undefined;
  /** The query string kept on rail links (view etc.), with its leading "?" or empty. */
  search: string;
  drawerOpen: boolean;
  onDrawerOpenChange: (open: boolean) => void;
}) {
  return (
    <>
      <aside className="reader-rail sticky top-topbar hidden h-[calc(100dvh-var(--topbar-h))] w-60 shrink-0 flex-col overflow-y-auto border-r border-line pt-2 md:flex lg:w-64">
        <RailContent scope={scope} filter={filter} counts={counts} search={search} />
      </aside>
      <Dialog.Root open={drawerOpen} onOpenChange={onDrawerOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="reader-drawer-overlay fixed inset-0 z-50 bg-black/50 md:hidden" />
          <Dialog.Content
            aria-describedby={undefined}
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
            <RailContent scope={scope} filter={filter} counts={counts} search={search} onNavigate={() => onDrawerOpenChange(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
