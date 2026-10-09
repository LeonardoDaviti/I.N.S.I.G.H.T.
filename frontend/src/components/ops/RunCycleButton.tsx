import { useId, useState } from 'react';
import { Loader2, Play } from 'lucide-react';

import type { RunReport } from '../../services/api';
import { useIngestionRun } from '../../hooks/useIngestionRun';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';
import ConfirmDialog from './ConfirmDialog';

/**
 * The manual "Run cycle" (spec §F.3): fetch the sources that are due, exactly as
 * the scheduler's next tick would. "Force all" ignores cadence and backoff (never
 * unavailability) and asks for a confirmation first, because it hits every source.
 */
export default function RunCycleButton({
  onReport,
  compact = false,
  className = '',
}: {
  onReport?: (report: RunReport) => void;
  /** A single-line variant for headers. */
  compact?: boolean;
  className?: string;
}) {
  const { run, isRunning } = useIngestionRun({ onReport: (report) => onReport?.(report) });
  const [force, setForce] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const forceId = useId();
  const running = isRunning({ kind: 'all' });

  const start = (forced: boolean) => {
    void run({ kind: 'all', force: forced });
  };

  const onClick = () => {
    if (force) setConfirming(true);
    else start(false);
  };

  const label = running ? 'Running…' : force ? 'Force all sources' : 'Run due sources';

  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-2 ${className}`}>
      <button
        type="button"
        onClick={onClick}
        disabled={running}
        aria-busy={running}
        className={`inline-flex min-h-[44px] items-center gap-2 rounded-lg px-4 text-sm font-medium disabled:opacity-60 ${PRESS_FEEDBACK} ${FOCUS_RING} ${
          force
            ? 'border border-[var(--text-error)] bg-[var(--background-primary)] text-[var(--text-error)] hover:bg-[var(--background-secondary)]'
            : 'bg-[var(--interactive-accent)] text-[var(--text-on-accent)] hover:bg-[var(--interactive-accent-hover)]'
        } ${compact ? 'min-h-[40px] px-3' : ''}`}
      >
        {running
          ? <Loader2 aria-hidden="true" className="h-4 w-4 motion-safe:animate-spin" />
          : <Play aria-hidden="true" className="h-4 w-4" />}
        {label}
      </button>
      <label htmlFor={forceId} className="inline-flex min-h-[44px] cursor-pointer select-none items-center gap-2 text-sm text-[var(--text-muted)]">
        <input
          id={forceId}
          type="checkbox"
          checked={force}
          onChange={(event) => setForce(event.target.checked)}
          disabled={running}
          className="h-4 w-4 accent-[var(--interactive-accent)]"
        />
        Force all (ignore cadence &amp; backoff)
      </label>
      <ConfirmDialog
        open={confirming}
        title="Force fetch every source?"
        description={(
          <>
            <p>This ignores cadence and backoff and fetches every enabled source now, even the ones that are not due or are failing.</p>
            <p className="mt-2">Unavailable sources (yt-dlp off, no Telegram session) are still skipped. Use it sparingly: it is the run most likely to get a source rate-limited.</p>
          </>
        )}
        confirmLabel="Force fetch every source"
        destructive
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          start(true);
        }}
      />
    </div>
  );
}
