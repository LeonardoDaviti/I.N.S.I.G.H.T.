import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { SourceHealthRow } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { SOURCES_HEALTH_KEY } from '../../hooks/useSourcesHealth';
import { errorMessage } from '../../lib/apiError';
import { formatRelativeTime } from '../../lib/dates';
import { formatHours } from '../../lib/duration';
import { plural } from '../../lib/format';
import { shortAddress } from '../../lib/addresses';
import { Button } from '../ui';
import { Notice } from '../states';

const VIA: Record<string, string> = { address: 'Its address', 'home page': 'Its home page', post: 'Its newest posts' };

/**
 * A source silent far beyond its own rhythm (issue 0178), in the source sheet and Discover: how long, against how
 * often it usually posts; where the source doctor found it went (its address now landing on another site), and the
 * live feed found there, with "Switch to <address>" (the switch path: the source keeps its id, name, tracks and
 * posts) and "It stopped" (its silence is not shown again until it posts). INSIGHT never switches it by itself.
 */
export default function SilentNotice({ row, now, onSwitched, compact = false }: {
  row: SourceHealthRow; now: Date; onSwitched?: () => void; compact?: boolean;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<'switch' | 'stopped' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const silent = row.silent;
  if (!silent || done) return null;
  const replacement = silent.replacement;

  const act = async (what: 'switch' | 'stopped') => {
    setBusy(what);
    setError(null);
    try {
      if (what === 'switch' && replacement) {
        await api.switchSource(row.source_id, replacement.url);
        onSwitched?.();
      } else {
        await api.markSourceStopped(row.source_id);
      }
      setDone(true);
      void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const title = `Silent for ${plural(silent.days, 'day')}: it usually posts every ${formatHours(silent.usual_gap_hours)}.`;
  const looked = silent.looked_at
    ? replacement ? `INSIGHT found where it went: ${replacement.title} (${replacement.url}), ${replacement.via}.`
      : `INSIGHT looked where it went ${formatRelativeTime(silent.looked_at, now)} and found no live feed.`
    : null;
  return (
    <Notice tone="warning" title={title} message={looked ?? undefined} className={compact ? 'px-3 py-2' : ''}>
      {silent.moved.length ? (
        <ul className="mt-1 text-[0.8125rem] text-fg-2">
          {silent.moved.map((move) => (
            <li key={`${move.via}-${move.to}`} className="[overflow-wrap:anywhere]">
              {`${VIA[move.via] ?? move.via} now lands at ${shortAddress(move.to)}`}
            </li>
          ))}
        </ul>
      ) : null}
      {replacement?.latest?.length && !compact ? (
        <div className="mt-2 text-[0.8125rem]">
          <p className="font-semibold text-fg">Its latest posts</p>
          <ul className="mt-0.5 list-disc pl-5 text-fg-2">
            {replacement.latest.map((latest, index) => <li key={index} className="break-words">{latest}</li>)}
          </ul>
        </div>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {replacement ? (
          <Button size="sm" variant="primary" onClick={() => void act('switch')} disabled={busy !== null} aria-busy={busy === 'switch'}
            title="Keeps this source's name, tracks and posts; the next fetch reads the new address">
            {busy === 'switch' ? 'Switching…' : `Switch to ${shortAddress(replacement.url)}`}
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" onClick={() => void act('stopped')} disabled={busy !== null} aria-busy={busy === 'stopped'}
          title="Not shown again until it posts; nothing is switched off">
          It stopped
        </Button>
      </div>
      {error ? <p className="mt-1 text-[0.75rem] font-semibold text-fg">× {error}</p> : null}
    </Notice>
  );
}
