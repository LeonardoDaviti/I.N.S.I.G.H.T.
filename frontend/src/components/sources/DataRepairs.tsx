import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { errorMessage } from '../../lib/apiError';
import { formatRelativeTime } from '../../lib/dates';
import { useNow } from '../../hooks/useNow';
import {
  countsLine, dataRepairsApi, repairsBusy, sampleHref, type DataRepair, type RepairMode, type RepairResult,
} from '../../services/dataRepairs';
import { Button, ExternalLink, TextLink } from '../ui';

export const DATA_REPAIRS_KEY = ['operations', 'repairs'] as const;

function Result({ result, label, now }: { result: RepairResult; label: string; now: Date }) {
  return (
    <div className="space-y-1" data-repair-result={result.dry_run ? 'preview' : 'run'}>
      <p className="text-[0.8125rem] tabular-nums text-fg-2">
        <span className="font-medium text-fg">{label}</span>
        {` · ${formatRelativeTime(result.at, now)} · ${result.version}`}
        {result.error ? null : ` · ${result.dry_run ? 'would change: ' : ''}${countsLine(result.counts)}`}
      </p>
      {result.error ? <p role="alert" className="text-[0.8125rem] text-fg">Failed: {result.error}</p> : null}
      {result.sample?.length ? (
        <ul className="space-y-0.5 text-[0.8125rem] text-fg-3" aria-label={`${label}: a sample`}>
          {result.sample.map((s, n) => {
            const href = sampleHref(s);
            return (
              <li key={n} className="[overflow-wrap:anywhere]">
                {href === null ? s.label : href.external
                  ? <ExternalLink href={href.to}>{s.label}</ExternalLink>
                  : <TextLink to={href.to}>{s.label}</TextLink>}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

function state(r: DataRepair): string {
  if (r.running) return r.running === 'preview' ? 'Previewing now…' : 'Running now…';
  if (r.requested) return r.requested === 'preview' ? 'Preview asked: the jobs process runs it shortly' : 'Run asked: the jobs process runs it shortly';
  if (r.due) return r.last_run?.error ? 'Failed; tried again at the next start' : 'Runs at the next start';
  return `Done for ${r.ran_version}`;
}

/**
 * v10.43: Data repairs, in Sources → ingestion → overview. One-time repairs run by themselves after a deploy (in the
 * jobs process, once per version); each shows its last run (when, what it changed, a sample with links) and its last
 * preview. "Run again" and "Preview" ask the jobs process; the page never runs a repair. No undo: the repairs keep
 * the old values in each row, but none keeps the whole way back simply.
 */
export default function DataRepairs({ titleClass }: { titleClass: string }) {
  const client = useQueryClient();
  const now = useNow(30_000);
  const repairs = useQuery({
    queryKey: [...DATA_REPAIRS_KEY],
    queryFn: () => dataRepairsApi.list(),
    refetchInterval: (query) => (repairsBusy(query.state.data?.repairs) ? 5_000 : 60_000),
  });
  const ask = useMutation({
    mutationFn: ({ name, mode }: { name: string; mode: RepairMode }) => dataRepairsApi.ask(name, mode),
    onSuccess: (row) => client.setQueryData([...DATA_REPAIRS_KEY], (old: { repairs: DataRepair[] } | undefined) =>
      old ? { repairs: old.repairs.map((r) => (r.name === row.name ? row : r)) } : old),
  });
  return (
    <section aria-labelledby="ingestion-repairs" className="space-y-3">
      <h2 id="ingestion-repairs" className={titleClass}>Data repairs</h2>
      <p className="text-[0.8125rem] text-fg-3">
        One-time fixes to stored data, run by themselves after an update. Nothing is deleted; each change keeps the old value.
      </p>
      {repairs.data ? (
        <ul className="divide-y divide-line border-y border-line">
          {repairs.data.repairs.map((r) => {
            const waiting = r.requested !== null || r.running !== null;
            return (
              <li key={r.name} data-repair={r.name} className="space-y-1.5 py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-[0.9375rem] font-medium text-fg">{r.title}</h3>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" disabled={waiting || ask.isPending}
                      onClick={() => ask.mutate({ name: r.name, mode: 'preview' })}>Preview</Button>
                    <Button size="sm" variant="ghost" disabled={waiting || ask.isPending}
                      onClick={() => ask.mutate({ name: r.name, mode: 'run' })}>Run again</Button>
                  </div>
                </div>
                <p className="text-[0.8125rem] text-fg-2">{r.about}</p>
                <p className="text-[0.8125rem] text-fg-3" role="status">{state(r)}</p>
                {r.last_run ? <Result result={r.last_run} label="Last run" now={now} /> : null}
                {r.last_preview ? <Result result={r.last_preview} label="Last preview" now={now} /> : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-[0.875rem] text-fg-2">
          {repairs.isError ? 'Could not read the data repairs.' : 'Reading the data repairs…'}
        </p>
      )}
      {ask.isError ? <p role="alert" className="text-[0.8125rem] text-fg">Not asked: {errorMessage(ask.error)}</p> : null}
    </section>
  );
}
