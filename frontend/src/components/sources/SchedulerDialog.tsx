import { useState } from 'react';

import type { SchedulerConfig } from '../../services/api';
import { Button, Dialog, DialogContent, DialogFooter, Input } from '../ui';

const fieldLabel = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';

/**
 * The scheduler's settings, shared by Sources → ingestion and the analysis-on
 * ingestion page. Reading-only it is the tick interval and the
 * sources.json sync; with analysis on, the briefing interval and toggles too.
 * Numbers are edited as text and clamped on save, so clearing a field to type
 * a new value works.
 */
export default function SchedulerDialog({
  open,
  config,
  analysis,
  onClose,
  onSave,
}: {
  open: boolean;
  config: SchedulerConfig;
  analysis: boolean;
  onClose: () => void;
  onSave: (next: SchedulerConfig) => Promise<boolean>;
}) {
  const [tick, setTick] = useState(String(config.ingest_tick_minutes ?? 60));
  const [interval, setIntervalHours] = useState(String(config.interval_hours));
  const [toggles, setToggles] = useState(() => ({
    sync_sources_each_cycle: config.sync_sources_each_cycle,
    generate_daily_briefing: config.generate_daily_briefing,
    generate_topic_briefing: config.generate_topic_briefing,
  }));
  const [saving, setSaving] = useState(false);
  const rows: Array<[keyof typeof toggles, string]> = [
    ['sync_sources_each_cycle', 'Sync sources.json every cycle'],
    ...(analysis ? [
      ['generate_daily_briefing', 'Write the daily briefing'],
      ['generate_topic_briefing', 'Write the topic briefing'],
    ] as Array<[keyof typeof toggles, string]> : []),
  ];

  const submit = async () => {
    setSaving(true);
    const saved = await onSave({
      ...config,
      ...toggles,
      ingest_tick_minutes: Math.max(15, Math.round(Number(tick)) || 15),
      interval_hours: Math.max(0.25, Number(interval) || 0.25),
    });
    setSaving(false);
    if (saved) onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent
        title="Scheduler"
        description={analysis ? 'How often the scheduler looks for due sources and writes briefings.' : 'How often the scheduler looks for due sources.'}
      >
        <form className="mt-5 space-y-5" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="ingestion-tick" className={fieldLabel}>Check for due sources every (minutes)</label>
              <Input id="ingestion-tick" type="number" min={15} step={5} value={tick} onChange={(e) => setTick(e.target.value)} className="tabular-nums" />
              <p className="mt-1 text-[0.75rem] text-fg-3">At least 15. Each source still waits for its own cadence.</p>
            </div>
            {analysis ? (
              <div>
                <label htmlFor="ingestion-interval" className={fieldLabel}>Write briefings every (hours)</label>
                <Input id="ingestion-interval" type="number" min={0.25} step={0.25} value={interval} onChange={(e) => setIntervalHours(e.target.value)} className="tabular-nums" />
              </div>
            ) : null}
          </div>
          <fieldset className="divide-y divide-line rounded-md border border-line">
            <legend className="sr-only">Each cycle</legend>
            {rows.map(([key, text]) => (
              <label key={key} className="flex min-h-[2.75rem] cursor-pointer items-center justify-between gap-3 px-3 text-[0.875rem] text-fg">
                <span>{text}</span>
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[rgb(var(--text))]"
                  checked={Boolean(toggles[key])}
                  onChange={(e) => setToggles((prev) => ({ ...prev, [key]: e.target.checked }))}
                />
              </label>
            ))}
          </fieldset>
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
