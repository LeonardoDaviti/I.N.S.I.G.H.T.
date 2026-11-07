import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import type { VoiceEvidence, VoicePair, VoiceSource, VoiceSuggestion } from '../../services/api';
import { voicesApi } from '../../services/voices';
import { Button } from '../ui';
import { EmptyState, ErrorState, LoadingState } from '../states';
import { errorMessage } from '../../lib/apiError';
import { formatRelativeTime } from '../../lib/dates';
import { formatCount, plural } from '../../lib/format';
import { getPlatformLabel, sourceLabel } from '../../lib/sourceLabel';
import { sourceReadPath } from '../../lib/feedContext';
import { VOICES_KEY } from '../../hooks/useVoice';

export const SUGGESTED_VOICES_KEY = [...VOICES_KEY, 'suggestions'] as const;

function SourceLine({ source }: { source: VoiceSource }) {
  return (
    <li className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-[0.875rem] leading-6">
      <Link to={sourceReadPath(source.id)} className="min-w-0 font-semibold text-fg underline decoration-transparent hover:decoration-fg-3 [overflow-wrap:anywhere]">
        {sourceLabel(source.name)}
      </Link>
      <span className="text-fg-3">
        {getPlatformLabel(source.kind)} · {plural(source.posts, 'post')}{source.enabled ? '' : ' · off'}
      </span>
    </li>
  );
}

function EvidenceLines({ evidence }: { evidence: VoiceEvidence[] }) {
  return (
    <ul className="mt-1 flex flex-col gap-0.5">
      {evidence.map((line, i) => (
        <li key={`${line.rule}-${i}`} className="text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          {line.line}
          {line.posts.length ? (
            <span className="text-fg-3">
              {' '}· {line.posts.map((id, k) => (
                <span key={id}>{k ? ', ' : ''}<Link to={`/posts/${encodeURIComponent(id)}`} className="underline decoration-fg-3">post {k + 1}</Link></span>
              ))}
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Every evidence line of a suggestion, each once. */
function allEvidence(suggestion: VoiceSuggestion): VoiceEvidence[] {
  const seen = new Set<string>();
  return suggestion.edges.flatMap((edge) => edge.evidence).filter((e) => (seen.has(e.line) ? false : (seen.add(e.line), true)));
}

/**
 * "Suggested voices" (issue 0132 A): the sources that look like one voice, each with its evidence, never joined
 * without you. Join makes them one voice (stories then count it once; only their posts regroup); Not the same keeps
 * them apart for good. Related voices (a company's staff) and name-only pairs ("possible") are listed apart.
 */
export default function SuggestedVoices() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: SUGGESTED_VOICES_KEY,
    queryFn: () => voicesApi.suggestions(),
    refetchInterval: (q) => (q.state.data?.computing ? 3_000 : false),
  });
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (key: string, run: () => Promise<unknown>, done: string) => {
    setBusy(key);
    try {
      await run();
      toast.success(done);
      await queryClient.invalidateQueries({ queryKey: VOICES_KEY });
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  if (query.isPending) return <LoadingState label="Loading suggested voices" rows={3} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Could not load suggested voices" />;
  const data = query.data;
  const pairsApart = (s: VoiceSuggestion) => s.edges.map((e) => () => voicesApi.notSame(e.a, e.b, e.evidence));

  return (
    <section aria-labelledby="suggested-voices" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="suggested-voices" className="text-[1rem] font-semibold text-fg">Suggested voices</h2>
        <p className="text-[0.8125rem] text-fg-3">
          {data.computing ? 'Looking at your sources…' : data.computed_at ? `Looked ${formatRelativeTime(data.computed_at)}` : null}{' '}
          <button type="button" className="underline decoration-fg-3 hover:text-fg" disabled={data.computing}
            onClick={() => void act('refresh', () => voicesApi.refresh(), 'Looking again')}>Look again</button>
        </p>
      </div>
      {data.voices.length === 0 ? (
        <EmptyState title={data.computing ? 'Looking at your sources' : 'No suggested voices'}
          description="Sources that look like one person, company or publication show here, each with why." />
      ) : (
        <ul className="flex flex-col">
          {data.voices.map((s) => (
            <li key={s.key} data-testid="voice-suggestion" className="border-b border-line py-3 last:border-b-0">
              {s.same_channel ? <p className="text-[0.8125rem] font-semibold leading-5 text-fg">The same channel twice: disable one?</p> : null}
              <ul>{s.sources.map((source) => <SourceLine key={source.id} source={source} />)}</ul>
              <EvidenceLines evidence={allEvidence(s)} />
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" disabled={busy !== null}
                  onClick={() => void act(s.key, () => voicesApi.join(s.sources.map((x) => x.id), { evidence: allEvidence(s) }),
                    `Joined ${formatCount(s.sources.length)} sources into one voice`)}>
                  Join
                </Button>
                <Button size="sm" variant="ghost" disabled={busy !== null}
                  onClick={() => void act(s.key, () => Promise.all(pairsApart(s).map((run) => run())), 'Kept apart')}>
                  Not the same
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <PairList title="Related voices" pairs={data.related} busy={busy}
        note="A company's staff or a close reposter: linked, never one voice. Each needs a bio until profiles are read."
        first={{ label: 'Related', run: (p) => voicesApi.related(p.a.id, p.b.id, p.evidence), done: 'Linked as related voices' }}
        onAct={act} />
      <PairList title="Possible" pairs={data.possible} busy={busy}
        note="A shared name and nothing else: never suggested. Join them only if you know they are one."
        first={{ label: 'Join', run: (p) => voicesApi.join([p.a.id, p.b.id], { evidence: p.evidence, byHand: true }), done: 'Joined into one voice' }}
        onAct={act} />
    </section>
  );
}

function PairList({ title, note, pairs, busy, first, onAct }: {
  title: string; note: string; pairs: VoicePair[]; busy: string | null;
  first: { label: string; run: (pair: VoicePair) => Promise<unknown>; done: string };
  onAct: (key: string, run: () => Promise<unknown>, done: string) => Promise<void>;
}) {
  if (!pairs.length) return null;
  return (
    <section aria-label={title}>
      <h3 className="text-[0.9375rem] font-semibold text-fg">{title}</h3>
      <p className="text-[0.8125rem] leading-5 text-fg-3">{note}</p>
      <ul className="flex flex-col">
        {pairs.map((pair) => {
          const key = `${pair.a.id}|${pair.b.id}`;
          return (
            <li key={key} className="border-b border-line py-2 last:border-b-0">
              <ul><SourceLine source={pair.a} /><SourceLine source={pair.b} /></ul>
              <EvidenceLines evidence={pair.evidence} />
              <div className="mt-1 flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void onAct(key, () => first.run(pair), first.done)}>
                  {first.label}
                </Button>
                <Button size="sm" variant="ghost" disabled={busy !== null}
                  onClick={() => void onAct(key, () => voicesApi.notSame(pair.a.id, pair.b.id, pair.evidence), 'Kept apart')}>
                  Not the same
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
