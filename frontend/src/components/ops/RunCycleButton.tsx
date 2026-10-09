import { useId, useState } from 'react';
import { Play } from 'lucide-react';

import type { RunReport } from '../../services/api';
import { useIngestionRun } from '../../hooks/useIngestionRun';
import { Button } from '../ui';
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
      <Button
        variant={force ? 'danger' : 'primary'}
        size={compact ? 'sm' : 'md'}
        onClick={onClick}
        disabled={running}
        aria-busy={running}
      >
        {running ? null : <Play aria-hidden="true" />}
        {label}
      </Button>
      <label htmlFor={forceId} className="inline-flex min-h-[2.25rem] cursor-pointer select-none items-center gap-2 text-[0.8125rem] text-fg-2 coarse:min-h-[2.75rem]">
        <input
          id={forceId}
          type="checkbox"
          checked={force}
          onChange={(event) => setForce(event.target.checked)}
          disabled={running}
          className="h-4 w-4 accent-[rgb(var(--text))]"
        />
        Force all (ignore cadence and backoff)
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
