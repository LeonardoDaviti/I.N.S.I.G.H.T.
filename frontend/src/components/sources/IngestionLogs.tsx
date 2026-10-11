import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';

import { useApi } from '../../services/ApiContext';
import { formatRelativeTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import { Button, Select } from '../ui';
import { Notice } from '../states';

const sectionTitle = 'text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg';

/** How many lines a tail asks for (the backend allows up to 1,000). */
const TAIL_LINES = 200;

/** The logs the backend serves, until it names them itself. */
const DEFAULT_LOGS = ['application', 'errors', 'rss', 'reddit', 'youtube', 'telegram', 'automated'];

const LOG_LABELS: Record<string, string> = {
  application: 'Application',
  errors: 'Errors',
  rss: 'RSS',
  reddit: 'Reddit',
  youtube: 'YouTube',
  telegram: 'Telegram',
  automated: 'Automated operations',
  interactive: 'Interactive operations',
  recovery: 'Recovery operations',
};

const logLabel = (name: string) => LOG_LABELS[name] ?? name;

/**
 * Sources → ingestion → logs: the tail of one backend log file, newest at the
 * bottom. It refreshes every 30 seconds while the page is visible, or on Refresh.
 */
export default function IngestionLogs() {
  const api = useApi();
  const [name, setName] = useState('application');
  const tail = useQuery({
    queryKey: ['ingestion-logs', name],
    queryFn: async () => {
      const response = await api.getIngestionLogs(name, TAIL_LINES);
      if (response.success === false) throw new Error(response.error || 'Could not read the log.');
      return response;
    },
    refetchInterval: 30_000,
  });
  const logs = tail.data?.available_logs?.length ? tail.data.available_logs : DEFAULT_LOGS;
  const lines = tail.data?.lines ?? [];

  const meta = (() => {
    if (!tail.data) return tail.isPending ? 'Loading…' : null;
    if (!tail.data.exists) return `${logLabel(name)} · not written yet`;
    const updated = typeof tail.data.updated_at === 'number' ? `updated ${formatRelativeTime(new Date(tail.data.updated_at * 1000))}` : null;
    return [logLabel(name), `last ${plural(lines.length, 'line')}`, updated].filter(Boolean).join(' · ');
  })();

  return (
    <section aria-labelledby="ingestion-log" className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="ingestion-log" className={sectionTitle}>Log</h2>
        <div className="flex items-center gap-2">
          <Select aria-label="Log file" value={name} onChange={(event) => setName(event.target.value)}>
            {logs.map((option) => <option key={option} value={option}>{logLabel(option)}</option>)}
          </Select>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void tail.refetch()}
            aria-label="Refresh the log"
            title="Refresh"
            aria-busy={tail.isFetching}
          >
            <RefreshCw aria-hidden="true" className={tail.isFetching ? 'motion-safe:animate-spin' : undefined} />
          </Button>
        </div>
      </div>
      {meta ? <p className="text-[0.75rem] tabular-nums text-fg-3">{meta}</p> : null}
      {tail.isError ? (
        <Notice tone="error" title={`Could not read the log: ${tail.error.message}`} />
      ) : (
        <pre className="max-h-[36rem] overflow-auto whitespace-pre-wrap rounded-md border border-line p-3 font-mono text-[0.75rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          {tail.isPending ? 'Loading the log…' : lines.length ? lines.join('\n') : 'No lines in this log yet.'}
        </pre>
      )}
    </section>
  );
}
