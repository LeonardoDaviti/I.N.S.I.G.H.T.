import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Button } from '../ui';
import { plural } from '../../lib/format';
import { runLine, scoutApi, scoutLine, unreadLine, type ScoutCandidate } from '../../services/scout';

export const scoutKey = (id: string) => ['markx-track-scout', id] as const;

export function ScoutRow({ c, onDone }: { c: ScoutCandidate; onDone?: () => void }) {
  const follow = useMutation({
    mutationFn: (as: 'active' | 'passive') => scoutApi.follow(c.id, as),
    onSuccess: () => onDone?.(),
  });
  const not = useMutation({ mutationFn: () => scoutApi.notThis(c.id), onSuccess: () => onDone?.() });
  const busy = follow.isPending || not.isPending;
  return (
    <li className="border-b border-line py-2" data-scout-candidate={c.id}>
      <p className="text-[0.8125rem] leading-5 text-fg [overflow-wrap:anywhere]" title={c.follow_address ?? c.address}>
        {scoutLine(c)}
      </p>
      {c.why ? <p className="text-[0.75rem] leading-5 text-fg-3 [overflow-wrap:anywhere]">{c.why}</p> : null}
      <div className="mt-1 flex flex-wrap items-center gap-1" role="group" aria-label={`Follow ${c.name}?`}>
        {follow.isSuccess ? (
          <span className="text-[0.75rem] text-fg-2">Followed {follow.variables === 'active' ? 'as active' : 'as passive'}</span>
        ) : not.isSuccess ? (
          <span className="text-[0.75rem] text-fg-2">Not this one</span>
        ) : (
          <>
            <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={busy} onClick={() => follow.mutate('active')}>
              Follow as active
            </Button>
            <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={busy} onClick={() => follow.mutate('passive')}>
              Follow as passive
            </Button>
            <Button size="sm" variant="ghost" className="text-[0.75rem]" disabled={busy} onClick={() => not.mutate()}>
              Not this one
            </Button>
          </>
        )}
        {follow.isError || not.isError ? <span role="alert" className="text-[0.75rem] text-fg">× not saved</span> : null}
      </div>
    </li>
  );
}

/**
 * The Topic view's "Sources for this track" (issue 0148, Mark X): the scout's suggestions, ranked by how many of their
 * last posts the track's judge put in (30% at least), each with Follow as active / passive / Not this one; the sources
 * it brought and how they do since; what could not be read and why. "Find sources for this track" starts a scout.
 */
export default function TrackScout({ folderId }: { folderId: string }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: scoutKey(folderId),
    queryFn: () => scoutApi.page(folderId),
    staleTime: 15_000,
    retry: false,
    refetchInterval: (q) => {
      const status = q.state.data?.runs[0]?.status;
      return status === 'running' ? 5_000 : status === 'waiting' ? 30_000 : false;
    },
  });
  const start = useMutation({
    mutationFn: () => scoutApi.start(folderId),
    onSuccess: () => void client.invalidateQueries({ queryKey: scoutKey(folderId) }),
  });
  const refresh = () => void client.invalidateQueries({ queryKey: scoutKey(folderId) });
  const page = query.data;
  const run = page?.runs[0];
  const busy = run?.status === 'running' || start.isPending;
  const unreadable = page ? [...page.reads_badly, ...page.unreadable] : [];
  return (
    <section aria-label="Sources for this track" className="mb-6">
      <h2 className="flex flex-wrap items-baseline gap-2 border-b border-line pb-1 text-[0.8125rem] font-semibold text-fg-2">
        <span>Sources for this track{page?.suggested.length ? <span className="font-normal text-fg-3"> · {page.suggested.length}</span> : null}</span>
        <Button size="sm" variant="ghost" className="text-[0.75rem] font-normal" disabled={busy} onClick={() => start.mutate()}>
          Find sources for this track
        </Button>
      </h2>
      <p className="mt-1 text-[0.75rem] text-fg-3">
        Sources INSIGHT doesn’t read yet, each read once and judged by this track: shown when 30% or more of its last posts fit.
      </p>
      {start.isError ? <p role="alert" className="mt-1 text-[0.75rem] text-fg">× {String((start.error as Error).message)}</p> : null}
      {page ? (
        <>
          {runLine(run, page) ? <p className="mt-1 text-[0.75rem] tabular-nums text-fg-3">{runLine(run, page)}</p> : null}
          {page.suggested.length ? (
            <ul aria-label="Suggested sources">{page.suggested.map((c) => <ScoutRow key={c.id} c={c} onDone={refresh} />)}</ul>
          ) : run ? <p className="mt-2 text-[0.8125rem] text-fg-2">No source to suggest yet.</p> : null}
          {page.followed.length ? (
            <ul aria-label="Followed from the scout" className="mt-2">
              {page.followed.map((f) => (
                <li key={f.source_id} className="text-[0.75rem] leading-5 text-fg-3">
                  {f.name} ({f.as}) · {f.judged ? `${f.fits} of ${plural(f.judged, 'post')} fit since you followed it` : 'nothing judged since you followed it'}
                </li>
              ))}
            </ul>
          ) : null}
          {unreadable.length ? (
            <details className="mt-2 text-[0.75rem] text-fg-3">
              <summary>{plural(unreadable.length, 'source')} could not be read well</summary>
              <ul>{unreadable.map((c) => <li key={c.id} className="[overflow-wrap:anywhere]">{unreadLine(c)}</li>)}</ul>
            </details>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
