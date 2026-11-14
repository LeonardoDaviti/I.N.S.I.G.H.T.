import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { useApi } from '../../services/ApiContext';
import type { OfficialRow } from '../../services/api';
import { Button, ExternalLink, TextLink } from '../ui';
import { FOCUS_RING } from '../states';
import { errorMessage } from '../../lib/apiError';
import {
  filterLine, fromLine, groupRows, judgeLine, kindLabel, modeLine, proofLine, showLabel, type OfficialGroup,
} from '../../lib/official';

export const OFFICIAL_KEY = ['official-channels'] as const;

/** One row: the channel, whose it is, why, where it was found, how it was checked, and Undo when it was added. */
function Row({ row, onUndo, undoing }: { row: OfficialRow; onUndo: (row: OfficialRow) => void; undoing: boolean }) {
  const from = fromLine(row.from);
  const proof = proofLine(row.proof);
  const judge = judgeLine(row.judge);
  const filter = filterLine(row.filter, row.hidden_items);
  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-full sm:basis-0">
          <h4 className="text-[0.9375rem] font-semibold leading-6 text-fg [overflow-wrap:anywhere]">
            {row.follow ? <ExternalLink href={row.follow} title={row.follow}>{row.key}</ExternalLink> : row.key}
            <span className="ml-2 text-[0.75rem] font-normal text-fg-3">
              {kindLabel(row.kind)}
              {row.actor.name ? (
                <>
                  {' · '}
                  {row.actor.id ? <TextLink to={`/markx/entities/${row.actor.id}`}>{row.actor.name}</TextLink> : row.actor.name}
                </>
              ) : null}
            </span>
          </h4>
          {row.why ? <p className="text-[0.8125rem] leading-5 text-fg-2">{row.why}</p> : null}
          {from ? <p className="text-[0.8125rem] leading-5 text-fg-3">{from}</p> : null}
          {row.owned ? <p className="text-[0.8125rem] leading-5 text-fg-3">{row.owned}</p> : null}
          {proof ? <p className="text-[0.8125rem] leading-5 text-fg-3">{proof}</p> : null}
          {judge ? <p className="text-[0.8125rem] leading-5 text-fg-3">{judge}</p> : null}
          {filter ? <p className="text-[0.8125rem] leading-5 text-fg-3 [overflow-wrap:anywhere]">{filter}</p> : null}
          {row.events.length ? (
            <ul className="mt-1 flex flex-col border-l border-line pl-3">
              {row.events.slice(0, 2).map((event) => (
                <li key={event.story} className="min-w-0 truncate text-[0.8125rem] leading-5 text-fg-3">
                  <TextLink to={`/markx/stories/${event.story}`} className="text-fg" dir="auto">{event.headline || 'A story'}</TextLink>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        {row.state === 'added' ? (
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" variant="secondary" disabled={undoing} aria-busy={undoing} onClick={() => onUndo(row)}>
              {undoing ? 'Undoing…' : 'Undo'}
            </Button>
          </div>
        ) : null}
      </div>
    </li>
  );
}

/** A group of rows; a collapsed group shows a "Show N …" button first. */
function Group({ group, rows, onUndo, undoingId }: {
  group: OfficialGroup; rows: OfficialRow[]; onUndo: (row: OfficialRow) => void; undoingId: string | null;
}) {
  const [open, setOpen] = useState(!group.collapsed);
  const listId = `official-${group.id}`;
  return (
    <div className="mt-2">
      <h3 className="text-[0.75rem] font-medium text-fg-3">{group.title}</h3>
      {group.collapsed ? (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((value) => !value)}
          className={`-ml-1 rounded-sm px-1 text-left text-[0.8125rem] leading-5 text-fg-2 hover:text-fg ${FOCUS_RING}`}
        >
          {open ? `Hide ${group.noun}` : showLabel(group, rows.length)}
        </button>
      ) : null}
      {open ? (
        <ul id={listId}>
          {rows.map((row) => <Row key={row.id} row={row} onUndo={onUndo} undoing={undoingId === row.id} />)}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * Discover → "Official channels" (issue 0196): the channels the official-channels job found for the actors of your
 * stories (an X account, a Telegram or YouTube channel, a site's section, a repository's releases): why, where it was
 * found, how it is the actor's, what reading it found, and the worker's judgement. In Shadow nothing is added; when the
 * job is on, the channels it added automatically have Undo. Shows nothing when there is nothing.
 */
export default function OfficialChannels() {
  const api = useApi();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: [...OFFICIAL_KEY],
    queryFn: ({ signal }) => api.getOfficial(signal),
    staleTime: 60_000,
    retry: false,
  });
  const undo = useMutation({
    mutationFn: (row: OfficialRow) => api.undoOfficial(row.id),
    onSuccess: (_answer, row) => toast(`${row.key} is undone`),
    onError: (error: unknown, row) => toast.error(`Could not undo ${row.key}: ${errorMessage(error)}`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: [...OFFICIAL_KEY] }),
  });
  const data = query.data;
  const rows = data?.rows ?? [];
  if (!data || !rows.length) return null;
  const undoingId = undo.isPending ? undo.variables?.id ?? null : null;
  return (
    <section aria-label="Official channels" className="mb-2">
      <h2 className="pt-1 text-[0.75rem] font-medium text-fg-3">Official channels</h2>
      <p className="text-[0.75rem] text-fg-3">{modeLine(data)}</p>
      {groupRows(rows).map(({ group, rows: groupRowsList }) => (
        <Group key={group.id} group={group} rows={groupRowsList} onUndo={(row) => undo.mutate(row)} undoingId={undoingId} />
      ))}
    </section>
  );
}
