import { useQuery, useQueryClient } from '@tanstack/react-query';

import { useMarkxOn } from '../../hooks/useMarkxOn';
import { folderReadPath } from '../../lib/feedContext';
import { scoutApi, type ScoutCandidate } from '../../services/scout';
import TextLink from '../ui/TextLink';
import { ScoutRow } from './TrackScout';

const KEY = ['markx-scout-suggestions'] as const;

/**
 * Discover's rows from the track scout (issue 0148, Mark X): each track's suggested sources under the track's name, the
 * same rows and buttons as its Topic view. Nothing while Mark X is off or nothing is suggested.
 */
export default function ScoutSourceLines() {
  const on = useMarkxOn();
  const client = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: () => scoutApi.suggestions(), enabled: on, staleTime: 60_000, retry: false });
  if (!on || !query.data?.length) return null;
  const byTrack = new Map<string, { name: string; rows: ScoutCandidate[] }>();
  for (const c of query.data) {
    const id = c.track ?? '';
    const group = byTrack.get(id) ?? { name: c.track_name ?? '', rows: [] };
    group.rows.push(c);
    byTrack.set(id, group);
  }
  return (
    <>
      {[...byTrack.entries()].map(([id, g]) => (
        <section key={id} aria-label={`Sources for ${g.name}`} className="mb-4 border-b border-line pb-3">
          <h2 className="text-[0.8125rem] font-semibold text-fg-2">
            Sources for <TextLink to={`${folderReadPath(id)}?view=topic`} muted>{g.name}</TextLink>
          </h2>
          <ul>{g.rows.map((c) => <ScoutRow key={c.id} c={c} onDone={() => void client.invalidateQueries({ queryKey: KEY })} />)}</ul>
        </section>
      ))}
    </>
  );
}
