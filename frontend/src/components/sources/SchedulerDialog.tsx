import { useState } from 'react';

import type { SchedulerConfig } from '../../services/api';
import { Button, Dialog, DialogContent, DialogFooter, Input, Switch } from '../ui';

const fieldLabel = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';

/**
 * The scheduler's settings under Sources → ingestion: the tick interval. The number is edited
 * as text and clamped on save, so clearing the field to type a new value works.
 */
export default function SchedulerDialog({
  open,
  config,
  onClose,
  onSave,
}: {
  open: boolean;
  config: SchedulerConfig;
  onClose: () => void;
  onSave: (next: SchedulerConfig) => Promise<boolean>;
}) {
  const [tick, setTick] = useState(String(config.ingest_tick_minutes ?? 60));
  // On unless you switched it off (issue 0126): the API sends the stored choice.
  const [collect, setCollect] = useState(config.collect_originals ?? true);
  // Off unless you switch it on (issue 0138 C).
  const [lookup, setLookup] = useState(config.lookup_originals ?? false);
  // On unless you switch it off (issue 0138 E1).
  const [classics, setClassics] = useState(config.store_classics ?? true);
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    setSaving(true);
    const saved = await onSave({
      ...config,
      ingest_tick_minutes: Math.max(15, Math.round(Number(tick)) || 15),
      collect_originals: collect,
      lookup_originals: lookup,
      store_classics: classics,
    });
    setSaving(false);
    if (saved) onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent
        title="Scheduler"
        description="How often the scheduler looks for due sources."
      >
        <form className="mt-5 space-y-5" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="ingestion-tick" className={fieldLabel}>Check for due sources every (minutes)</label>
              <Input id="ingestion-tick" type="number" min={15} step={5} value={tick} onChange={(e) => setTick(e.target.value)} className="tabular-nums" />
              <p className="mt-1 text-[0.75rem] text-fg-3">At least 15. Each source still waits for its own cadence.</p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Switch id="collect-originals" checked={collect} onCheckedChange={setCollect} className="mt-0.5" />
            <div>
              <label htmlFor="collect-originals" className="text-[0.8125rem] font-medium text-fg">Collect originals</label>
              <p className="mt-0.5 text-[0.75rem] text-fg-3">
                When a News story starts at a page you don&rsquo;t have, fetch that one page, without following its site.
                Also the paper or release page of a thing two of your sources write about. Never a paywalled page; at
                most 1% more requests than the schedule makes. On unless you switch it off.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Switch id="lookup-originals" checked={lookup} onCheckedChange={setLookup} className="mt-0.5" />
            <div>
              <label htmlFor="lookup-originals" className="text-[0.8125rem] font-medium text-fg">Look up unlinked originals</label>
              <p className="mt-0.5 text-[0.75rem] text-fg-3">
                When two of your sources write about a paper and none links it, look it up once by its title (arXiv, then
                Crossref). Within the same budget. Off unless you switch it on.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Switch id="store-classics" checked={classics} onCheckedChange={setClassics} className="mt-0.5" />
            <div>
              <label htmlFor="store-classics" className="text-[0.8125rem] font-medium text-fg">Store Classics</label>
              <p className="mt-0.5 text-[0.75rem] text-fg-3">
                Keep every Classic you don&rsquo;t have, and a work site two of your sources link (a report, an essay
                series) with its pages they link: up to 100 pages a day, one site at a time. Never a product&rsquo;s or
                an app&rsquo;s site, never a paywalled page. On unless you switch it off.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
