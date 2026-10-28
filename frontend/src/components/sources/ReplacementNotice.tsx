import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { SourceHealthRow, SourceReplacement } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { SOURCES_HEALTH_KEY } from '../../hooks/useSourcesHealth';
import { errorMessage } from '../../lib/apiError';
import { formatRelativeTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import { Button } from '../ui';
import { Notice } from '../states';

/** What the replacement is, in words: "Arena blog (https://arena.ai/blog/feed.xml)" or
 *  "Follow arena.ai/blog: 76 articles". */
function replacementLabel(replacement: SourceReplacement): string {
  if (replacement.kind === 'page_watch') return `Follow ${replacement.title}: ${plural(replacement.found ?? 0, 'article')}`;
  return `${replacement.title} (${replacement.url})`;
}

/**
 * The source doctor's finding on a broken source (issue 0036), in the source sheet: the
 * replacement it found, with Switch (the source keeps its name, tracks and posts) and
 * Dismiss (until the next failure streak), or that it looked and found none.
 */
export default function ReplacementNotice({ row, now, onSwitched }: { row: SourceHealthRow; now: Date; onSwitched: () => void }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<'switch' | 'dismiss' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const { replacement, doctor_looked_at: lookedAt } = row;
  if (!lookedAt || done) return null;

  const title = 'This source stopped working.';
  if (!replacement) {
    return (
      <Notice tone="warning" title={title} message={`INSIGHT looked for a replacement ${formatRelativeTime(lookedAt, now)} and found none.`} />
    );
  }

  const act = async (what: 'switch' | 'dismiss') => {
    setBusy(what);
    setError(null);
    try {
      if (what === 'switch') {
        await api.switchSource(row.source_id, replacement.url,
          replacement.kind === 'page_watch' ? (replacement.prefix ? { prefix: replacement.prefix } : {}) : undefined);
        onSwitched();
      } else {
        await api.dismissReplacement(row.source_id);
      }
      setDone(true);
      void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Notice tone="warning" title={title} message={`INSIGHT found a replacement: ${replacementLabel(replacement)}`}>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" onClick={() => void act('switch')} disabled={busy !== null} aria-busy={busy === 'switch'}
          title="Keeps this source's name, tracks and posts; the next fetch reads the new address">
          {busy === 'switch' ? 'Switching…' : 'Switch'}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void act('dismiss')} disabled={busy !== null}>
          Dismiss
        </Button>
      </div>
      {error ? <p className="mt-1 text-[0.75rem] font-semibold text-fg">× {error}</p> : null}
    </Notice>
  );
}
