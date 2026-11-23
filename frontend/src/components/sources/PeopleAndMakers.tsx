import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { useApi } from '../../services/ApiContext';
import type { PeopleRow } from '../../services/api';
import { Button, ExternalLink } from '../ui';
import { FOCUS_RING } from '../states';
import { plural } from '../../lib/format';
import { untitledLine } from '../../lib/discover';

export const PEOPLE_KEY = ['discover-people'] as const;

/** Where a row is followed: an author's address, else a maker's first channel the official module found. */
export function followAddress(row: PeopleRow): string | null {
  if (row.kind === 'author') return row.follow?.address ?? null;
  return row.channels?.find((c) => c.address)?.address ?? null;
}

function whereLabel(where: string): string {
  return where === 'news' ? 'News' : where.replace(/^track:/, '');
}

/** One row: name · kind · N posts · tracks, Follow… (Add source), the posts on expand. */
function Row({ row, onFollow }: { row: PeopleRow; onFollow: (url: string) => void }) {
  const [open, setOpen] = useState(false);
  const listId = `people-${row.key.replace(/[^a-z0-9]+/gi, '-')}`;
  const address = followAddress(row);
  const where = [...row.tracks, ...(row.news ? ['News'] : [])].join(', ');
  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-full sm:basis-0">
          <h3 className="text-[0.9375rem] font-semibold leading-6 text-fg [overflow-wrap:anywhere]" dir="auto">
            {row.name}
            <span className="ml-2 text-[0.75rem] font-normal text-fg-3">
              {row.kind === 'maker' ? 'maker' : row.platform} · {plural(row.posts, 'post')}{where ? ` · ${where}` : ''}
            </span>
          </h3>
          {row.kind === 'author' && row.accounts.length ? (
            <p className="truncate text-[0.8125rem] leading-5 text-fg-3" title={row.accounts.join(', ')}>{row.accounts.join(' · ')}</p>
          ) : null}
          {row.kind === 'maker' && !address ? (
            <p className="text-[0.8125rem] leading-5 text-fg-3">Its own channels are not found yet</p>
          ) : null}
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((value) => !value)}
            className={`-ml-1 inline-flex max-w-full items-start gap-1 rounded-sm px-1 text-left text-[0.8125rem] leading-5 text-fg-2 hover:text-fg ${FOCUS_RING}`}
          >
            {open ? <ChevronDown aria-hidden="true" className="mt-1 h-3 w-3 shrink-0" /> : <ChevronRight aria-hidden="true" className="mt-1 h-3 w-3 shrink-0" />}
            <span>The posts that brought {row.kind === 'maker' ? 'it' : 'them'}</span>
          </button>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {address ? (
            <Button size="sm" variant="secondary" title={address} onClick={() => onFollow(address)}>Follow…</Button>
          ) : null}
        </div>
      </div>
      {open ? (
        <ul id={listId} className="mt-2 flex flex-col gap-1 border-l border-line pl-3">
          {row.evidence.map((post) => (
            <li key={post.post_id} className="flex min-w-0 items-baseline gap-1.5 text-[0.8125rem] leading-5 text-fg-3">
              {post.url ? (
                <ExternalLink href={post.url} dir="auto" className="min-w-0 truncate" title={post.url}>{post.title || untitledLine(post.url)}</ExternalLink>
              ) : <span className="min-w-0 truncate" dir="auto">{post.title}</span>}
              <span className="shrink-0">· {whereLabel(post.where)} · {post.how}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** Discover → "People and makers your tracks quote": the accounts your tracks' posts and News quote, repost, mention
 *  or link, and the makers of what they name, ranked by those posts (30 days). Nothing is followed here. */
export default function PeopleAndMakers({ onFollow }: { onFollow: (url: string) => void }) {
  const api = useApi();
  const query = useQuery({
    queryKey: [...PEOPLE_KEY],
    queryFn: ({ signal }) => api.getDiscoverPeople(signal),
    staleTime: 60_000,
    retry: false,
  });
  const rows = [...(query.data?.authors ?? []), ...(query.data?.makers ?? [])];
  if (!rows.length) return null;
  return (
    <section aria-label="People and makers your tracks quote" className="mb-2">
      <h2 className="pt-1 text-[0.75rem] font-medium text-fg-3">People and makers your tracks quote</h2>
      <p className="text-[0.75rem] text-fg-3">
        Who your tracks&rsquo; posts and News of the last {query.data?.window_days ?? 30} days quote, repost, mention or link, and the makers of what they name.
      </p>
      <ul>
        {rows.map((row) => <Row key={row.key} row={row} onFollow={onFollow} />)}
      </ul>
    </section>
  );
}
