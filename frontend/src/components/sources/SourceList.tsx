import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, ChevronRight, RefreshCw } from 'lucide-react';

import type { SourceHealthRow } from '../../services/api';
import { HEALTH_STATUS_LABELS, formatDue } from '../../lib/sourceSchedule';
import { formatCount, plural } from '../../lib/format';
import { cn } from '../../lib/utils';
import { StatusGlyph, Switch } from '../ui';
import TrackMenu from './TrackMenu';
import { STATUS_GLYPH, compactAge, kindLabel, lastPostAt, rowFact, rowName, type SourceGroup } from './sourceList';
import { folderReadPath } from '../../lib/feedContext';

/** A native checkbox in the ink colour (the browser picks a contrasting tick in both themes). */
const CHECKBOX =
  'h-4 w-4 shrink-0 cursor-pointer [accent-color:rgb(var(--text))] coarse:h-5 coarse:w-5 '
  + 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg';

/**
 * Checkboxes stay out of the reading path: they appear on row hover or focus
 * and once anything is selected; on touch (no hover) they always show. They
 * keep their space, so nothing shifts when they appear.
 */
const REVEAL = 'opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100 focus:opacity-100 coarse:opacity-100';

/** The fixed columns, shared by the column header and every row so they line up. */
const COL = {
  kind: 'hidden w-[6.5rem] shrink-0 truncate sm:block',
  posts: 'w-[3.25rem] shrink-0 text-right tabular-nums',
  lastPost: 'hidden w-[3.25rem] shrink-0 text-right tabular-nums sm:block',
  note: 'hidden w-[8.5rem] shrink-0 truncate text-right tabular-nums md:block',
} as const;

export interface TrackActions {
  fetch: (folderId: string, name: string) => void;
  isFetching: (folderId: string) => boolean;
  rename: (folderId: string, name: string) => void;
  /** Whether the track's sources are in the main feed and digest; null while unknown. */
  inMainDigest: (folderId: string) => boolean | null;
  setMainDigest: (folderId: string, name: string, on: boolean) => void;
  remove: (folderId: string, name: string) => void;
}

export interface SourceListProps {
  groups: SourceGroup[];
  collapsed: ReadonlySet<string>;
  onToggleGroup: (key: string) => void;
  selected: ReadonlySet<string>;
  onSelect: (ids: string[], on: boolean) => void;
  /** A row checkbox changed; `shift` = shift-click (select the range from the last one). */
  onSelectRow: (key: string, id: string, on: boolean, shift: boolean) => void;
  activeKey: string | null;
  onActivate: (key: string) => void;
  onOpen: (id: string) => void;
  onToggleEnabled: (row: SourceHealthRow) => void;
  track: TrackActions;
  now: Date;
  /** Show every group header (false for the single "no grouping" list). */
  showHeaders: boolean;
  /** Focus the active row's name when activeKey changes by keyboard. */
  focusToken: number;
}

/**
 * The sources as one dense list (one 36px line per source), in groups whose
 * headers stick under the toolbar and collapse. Every row: select, status
 * glyph, name (opens the detail sheet), kind, posts, last new post, a status
 * note, on/off; on a phone only the glyph, name, posts and switch (never a
 * URL). Roving focus: only the active row's controls are tab stops; j/k move it.
 */
export default function SourceList({
  groups,
  collapsed,
  onToggleGroup,
  selected,
  onSelect,
  onSelectRow,
  activeKey,
  onActivate,
  onOpen,
  onToggleEnabled,
  track,
  now,
  showHeaders,
  focusToken,
}: SourceListProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const firstGroup = groups.find((g) => !collapsed.has(g.key) && g.rows.length);
  const fallbackKey = firstGroup ? `${firstGroup.key}/${firstGroup.rows[0].source_id}` : null;
  const tabKey = activeKey ?? fallbackKey;
  const selecting = selected.size > 0;

  useEffect(() => {
    if (!focusToken || !activeKey) return;
    const el = rootRef.current?.querySelector<HTMLElement>(`[data-row-key="${CSS.escape(activeKey)}"] [data-row-name]`);
    el?.focus();
    el?.scrollIntoView?.({ block: 'nearest' });
  }, [focusToken, activeKey]);

  return (
    <div ref={rootRef} className="min-w-0">
      {/* Column names for the numbers (pointer screens only; rows carry their own labels for AT). */}
      <div aria-hidden="true" className="hidden h-7 min-w-0 items-center gap-3 border-b border-line px-3 text-[0.6875rem] text-fg-3 sm:flex">
        <span className="w-4 shrink-0" />
        <span className="w-3.5 shrink-0" />
        <span className="min-w-0 flex-1">Name</span>
        <span className={COL.kind}>Kind</span>
        <span className={COL.posts}>Posts</span>
        <span className={COL.lastPost}>Last post</span>
        <span className={COL.note}>Status</span>
        <span className="w-9 shrink-0" />
      </div>
      {groups.map((group) => {
        const open = !collapsed.has(group.key);
        const ids = group.rows.map((row) => row.source_id);
        const picked = ids.filter((id) => selected.has(id)).length;
        const headerId = `group-${group.key}`;
        return (
          <section key={group.key} aria-labelledby={showHeaders ? headerId : undefined} aria-label={showHeaders ? undefined : group.label} className="min-w-0">
            {showHeaders ? (
              <div
                className="group/row material sticky top-[calc(var(--topbar-h)+var(--sources-toolbar-h,0px))] z-10 flex has-[[role=menu]]:z-[15] h-9 min-w-0 items-center gap-3 border-b border-line px-3"
              >
                <input
                  type="checkbox"
                  className={cn(CHECKBOX, !selecting && REVEAL, !ids.length && 'invisible')}
                  checked={ids.length > 0 && picked === ids.length}
                  ref={(el) => { if (el) el.indeterminate = picked > 0 && picked < ids.length; }}
                  onChange={(event) => onSelect(ids, event.target.checked)}
                  aria-label={`Select every source in ${group.label}`}
                  disabled={!ids.length}
                />
                <h2 id={headerId} className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => onToggleGroup(group.key)}
                    aria-expanded={open}
                    className="flex min-w-0 max-w-full items-center gap-1.5 rounded-sm text-left text-[0.8125rem] font-semibold text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
                  >
                    <ChevronRight aria-hidden="true" className={cn('h-3.5 w-3.5 shrink-0 text-fg-3', open && 'rotate-90')} />
                    <span className="min-w-0 truncate" dir="auto" title={group.label}>{group.label}</span>
                    <span className="shrink-0 font-normal tabular-nums text-fg-3">{formatCount(group.rows.length)}</span>
                  </button>
                </h2>
                {group.folderId ? (
                  <div className="-mr-2 flex shrink-0 items-center">
                    <button
                      type="button"
                      onClick={() => track.fetch(group.folderId!, group.label)}
                      disabled={track.isFetching(group.folderId)}
                      aria-busy={track.isFetching(group.folderId)}
                      aria-label={`Fetch track ${group.label}`}
                      title="Fetch this track now"
                      className="hidden h-8 w-8 sm:inline-flex items-center justify-center rounded-md text-fg-3 hover:bg-raised hover:text-fg disabled:cursor-default disabled:text-fg-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg coarse:h-11 coarse:w-11"
                    >
                      <RefreshCw aria-hidden="true" className={cn('h-3.5 w-3.5', track.isFetching(group.folderId) && 'motion-safe:animate-spin')} />
                    </button>
                    <Link
                      to={folderReadPath(group.folderId)}
                      aria-label={`Open track ${group.label}`}
                      title="Open track"
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-fg-3 hover:bg-raised hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg coarse:h-11 coarse:w-11"
                    >
                      <ArrowUpRight aria-hidden="true" className="h-4 w-4" />
                    </Link>
                    <TrackMenu
                      name={group.label}
                      inMainDigest={track.inMainDigest(group.folderId)}
                      onFetch={track.isFetching(group.folderId) ? undefined : () => track.fetch(group.folderId!, group.label)}
                      onRename={() => track.rename(group.folderId!, group.label)}
                      onMainDigest={(on) => track.setMainDigest(group.folderId!, group.label, on)}
                      onDelete={() => track.remove(group.folderId!, group.label)}
                    />
                  </div>
                ) : null}
              </div>
            ) : null}
            {open ? (
              group.rows.length ? (
                <ul className="min-w-0">
                  {group.rows.map((row) => {
                    const key = `${group.key}/${row.source_id}`;
                    const name = rowName(row);
                    const isActive = key === activeKey;
                    const tab = key === tabKey ? 0 : -1;
                    const status = row.enabled ? row.status : 'disabled';
                    const isSelected = selected.has(row.source_id);
                    const postedAt = lastPostAt(row);
                    return (
                      <li
                        key={key}
                        data-row-key={key}
                        data-source-id={row.source_id}
                        aria-current={isActive ? 'true' : undefined}
                        onFocusCapture={() => { if (!isActive) onActivate(key); }}
                        className={cn(
                          'group/row flex h-9 min-w-0 items-center gap-3 border-b border-line px-3 coarse:h-11',
                          'hover:bg-surface',
                          isActive && 'bg-surface shadow-[inset_2px_0_0_rgb(var(--text))]',
                          isSelected && 'bg-raised',
                        )}
                      >
                        <input
                          type="checkbox"
                          tabIndex={tab}
                          className={cn(CHECKBOX, !selecting && REVEAL)}
                          checked={isSelected}
                          onChange={(event) => {
                            // React drives a checkbox's change from its click, so the click's Shift is here.
                            const native = event.nativeEvent as Partial<MouseEvent>;
                            onSelectRow(key, row.source_id, event.target.checked, native.shiftKey === true);
                          }}
                          aria-label={`Select ${name}`}
                        />
                        <StatusGlyph
                          status={STATUS_GLYPH[status] ?? 'scheduled'}
                          label={HEALTH_STATUS_LABELS[status] ?? status}
                          hideLabel
                          className="w-3.5 justify-center"
                        />
                        <button
                          type="button"
                          data-row-name
                          tabIndex={tab}
                          onClick={() => onOpen(row.source_id)}
                          title={String(row.display_name)}
                          dir="auto"
                          className={cn(
                            'min-w-0 flex-1 truncate rounded-sm text-left text-[0.875rem] outline-none focus-visible:underline focus-visible:decoration-2 focus-visible:underline-offset-4',
                            row.enabled ? 'font-semibold text-fg' : 'text-fg-3',
                          )}
                        >
                          {name}
                        </button>
                        <span className={cn(COL.kind, 'text-[0.75rem] text-fg-3')}>{kindLabel(row)}</span>
                        <span
                          className={cn(COL.posts, 'text-[0.75rem]', row.stored_posts ? 'text-fg-2' : 'text-fg-3')}
                          title={plural(row.stored_posts, 'post')}
                        >
                          {formatCount(row.stored_posts)}<span className="sr-only"> posts</span>
                        </span>
                        <span
                          className={cn(COL.lastPost, 'text-[0.75rem] text-fg-3')}
                          title={postedAt ? `Newest post ${new Date(postedAt).toLocaleString()}` : 'No posts yet'}
                        >
                          <span className="sr-only">newest post </span>{compactAge(postedAt, now)}
                        </span>
                        <span
                          className={cn(
                            COL.note,
                            'text-[0.75rem]',
                            row.status === 'error' || row.status === 'backoff' ? 'font-medium text-fg' : 'text-fg-3',
                          )}
                          title={row.last_error ?? (row.next_due_at ? `next ${formatDue(row.next_due_at, now)}` : undefined)}
                        >
                          {rowFact(row, now)}
                        </span>
                        <Switch
                          checked={row.enabled}
                          tabIndex={tab}
                          onCheckedChange={() => onToggleEnabled(row)}
                          aria-label={`${row.enabled ? 'Disable' : 'Enable'} ${name}`}
                        />
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="border-b border-line px-3 py-2 pl-[3.25rem] text-[0.8125rem] text-fg-3">
                  No sources yet.
                </p>
              )
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
