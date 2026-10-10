import { useState } from 'react';
import { toast } from 'sonner';

import { useApi } from '../../services/ApiContext';
import { localDateISO } from '../../lib/dates';
import { Button, Input } from '../ui';

const sectionTitle = 'text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg';
const fieldLabel = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';

type Action = 'daily' | 'topics' | 'json-to-db' | 'db-to-json';

/**
 * The analysis-only controls of the old ingestion page: write a briefing, and
 * copy the source registry between sources.json and the database. Shown under
 * Sources → ingestion only with analysis on (reading-finish R3).
 */
export default function IngestionAnalysisActions({ onDone }: { onDone?: () => void }) {
  const api = useApi();
  const [date, setDate] = useState(() => localDateISO());
  const [running, setRunning] = useState<Action | null>(null);

  const run = async (action: Action, label: string, fn: () => Promise<{ success?: boolean; error?: string }>) => {
    setRunning(action);
    try {
      const result = await fn();
      if (result.success === false) toast.error(result.error || `${label} failed`);
      else toast.success(`${label} done`);
      onDone?.();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : `${label} failed`);
    } finally {
      setRunning(null);
    }
  };
  const busy = running !== null;

  return (
    <>
      <section aria-labelledby="ingestion-briefings" className="space-y-3">
        <h2 id="ingestion-briefings" className={sectionTitle}>Write a briefing</h2>
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-full sm:w-auto">
            <label htmlFor="ingestion-briefing-date" className={fieldLabel}>Date</label>
            <Input id="ingestion-briefing-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="tabular-nums sm:w-44" />
          </div>
          <Button variant="secondary" disabled={busy} onClick={() => void run('daily', 'Daily briefing', () => api.generateBriefing(date))}>
            {running === 'daily' ? 'Writing…' : 'Daily briefing'}
          </Button>
          <Button variant="secondary" disabled={busy} onClick={() => void run('topics', 'Topic briefing', () => api.generateBriefingWithTopics(date))}>
            {running === 'topics' ? 'Writing…' : 'Topic briefing'}
          </Button>
        </div>
      </section>

      <section aria-labelledby="ingestion-registry" className="space-y-3">
        <h2 id="ingestion-registry" className={sectionTitle}>Source registry</h2>
        <p className="text-[0.8125rem] text-fg-2">Copy the source list between <code className="font-mono text-[0.75rem]">sources.json</code> and the database.</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => void run('json-to-db', 'Registry sync', () => api.syncSources('json-to-db'))}>
            {running === 'json-to-db' ? 'Syncing…' : 'JSON → database'}
          </Button>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => void run('db-to-json', 'Registry sync', () => api.syncSources('db-to-json'))}>
            {running === 'db-to-json' ? 'Syncing…' : 'Database → JSON'}
          </Button>
        </div>
      </section>
    </>
  );
}
