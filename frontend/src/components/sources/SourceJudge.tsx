import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { useMarkxOn } from '../../hooks/useMarkxOn';
import { errorMessage } from '../../lib/apiError';
import { formatRelativeTime } from '../../lib/dates';
import { judgeLine, sourceJudgeApi, verdictWord, waitingLine, type SourceJudgement } from '../../services/sourceJudge';
import { Button, ExternalLink } from '../ui';
import { FOCUS_RING } from '../states';
import { untitledLine } from '../../lib/discover';

const KEY = 'source-judge';
/** How often an open judgement is looked at again: its read takes seconds, the worker's answer waits for its run. */
const READING_MS = 3_000;
const ASKED_MS = 20_000;

/** The verdict, its reasons, the items it relied on and what INSIGHT measured (folded). */
function Verdict({ j, onAgain, busy }: { j: SourceJudgement; onAgain: () => void; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const id = `judge-${j.id}`;
  return (
    <div className="mt-1.5 rounded-md border border-line px-3 py-2 text-[0.8125rem] leading-5" aria-label="The worker's judgement" role="group">
      <p className="text-fg">
        <span className="font-semibold">{j.verdict ? verdictWord(j.verdict) : ''}</span>
        <span className="text-fg-3">{judgeLine(j) ? ` · ${judgeLine(j)}` : ''}</span>
      </p>
      <ul className="mt-1 list-disc pl-4 text-fg-2">
        {j.reasons.map((r) => <li key={r}>{r}</li>)}
      </ul>
      {j.examples.length ? (
        <ul aria-label="Items it relied on" className="mt-1 flex flex-col gap-0.5 border-l border-line pl-3 text-fg-3">
          {j.examples.map((e) => (
            <li key={e.id} className="flex min-w-0 items-baseline gap-1.5">
              <ExternalLink href={e.url} dir="auto" className="min-w-0 truncate text-fg" title={e.url}>{e.title || untitledLine(e.url)}</ExternalLink>
              {e.published_at ? <span className="shrink-0">· {formatRelativeTime(e.published_at)}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] text-fg-3">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((v) => !v)}
          className={`-ml-1 inline-flex items-center gap-1 rounded-sm px-1 hover:text-fg ${FOCUS_RING}`}
        >
          {open ? <ChevronDown aria-hidden="true" className="h-3 w-3" /> : <ChevronRight aria-hidden="true" className="h-3 w-3" />}
          What INSIGHT measured
        </button>
        <span>
          {j.same_items ? 'Asked again: no new items, the same answer' : `Judged ${formatRelativeTime(j.answered_at ?? j.asked_at)}`}
        </span>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onAgain}>Ask again</Button>
      </div>
      {open ? (
        <ul id={id} className="mt-1 flex flex-col gap-0.5 text-[0.75rem] text-fg-3">
          {j.measured.map((m) => <li key={m} className="[overflow-wrap:anywhere]">{m}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * "Is this worth it?" (issue 0173, Mark X): on the owner's tap only, the worker reads the candidate's newest items with
 * what INSIGHT measured (who links it, the stories it started, its pace, how it reads, whether it repeats your sources)
 * and says follow, maybe or skip, with its reasons and the items it relied on. Nothing is followed: Follow stays the
 * row's own (the Add source dialog). An answer is kept 30 days; Ask again asks again only when it posted something new.
 * Nothing while Mark X is off.
 */
export default function SourceJudge({ address, compact = false }: { address: string; compact?: boolean }) {
  const on = useMarkxOn();
  const client = useQueryClient();
  const [asked, setAsked] = useState(false);
  const [busy, setBusy] = useState(false);
  const key = [KEY, address];
  const query = useQuery({
    queryKey: key,
    queryFn: async () => (await sourceJudgeApi.get(address)).judgement,
    enabled: on && asked,
    retry: false,
    refetchInterval: (q) => {
      const status = (q.state.data as SourceJudgement | null | undefined)?.status;
      return status === 'reading' ? READING_MS : status === 'asked' ? ASKED_MS : false;
    },
  });
  if (!on || !address) return null;
  const ask = (again: boolean) => {
    setBusy(true);
    void sourceJudgeApi.ask(address, again).then(
      (got) => {
        client.setQueryData(key, got.judgement);
        setAsked(true);
      },
      (error: unknown) => toast.error(`Could not ask about ${address}: ${errorMessage(error)}`),
    ).finally(() => setBusy(false));
  };
  const j = asked ? query.data : undefined;
  const waiting = j ? waitingLine(j) : null;
  return (
    <div className={compact ? 'min-w-0' : 'mt-1 min-w-0'}>
      {!j ? (
        <Button size="sm" variant="ghost" className="-ml-2" disabled={busy} onClick={() => ask(false)}>
          {busy ? 'Asking…' : 'Is this worth it?'}
        </Button>
      ) : j.status === 'answered' ? (
        <Verdict j={j} busy={busy} onAgain={() => ask(true)} />
      ) : (
        <p role="status" className="text-[0.8125rem] leading-5 text-fg-3">
          {waiting}
          {j.status === 'unreadable' || j.status === 'failed' ? (
            <Button size="sm" variant="ghost" className="ml-1" disabled={busy} onClick={() => ask(true)}>Try again</Button>
          ) : null}
        </p>
      )}
    </div>
  );
}
