import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { useApi } from '../../services/ApiContext';
import type { Voice } from '../../services/api';
import { voicesApi } from '../../services/voices';
import { Button, Dialog, DialogContent, DialogFooter, Input } from '../ui';
import { ErrorState, LoadingState } from '../states';
import { errorMessage } from '../../lib/apiError';
import { getPlatformLabel, sourceLabel } from '../../lib/sourceLabel';
import { plural } from '../../lib/format';
import { sourceReadPath, voiceReadPath } from '../../lib/feedContext';
import { VOICES_KEY } from '../../hooks/useVoice';
import SuggestedVoices from './SuggestedVoices';

/** "Make a voice" (issue 0132 A): any sources joined by hand, named by the main channel unless you name it. */
function MakeVoice({ onDone }: { onDone: () => void }) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [name, setName] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const sources = useQuery({ queryKey: ['sources', 'for-voices'], queryFn: () => api.getSources(), enabled: open });
  const shown = useMemo(() => {
    const words = filter.trim().toLowerCase();
    return (sources.data?.sources ?? [])
      .map((s) => ({ id: s.id, name: s.settings?.display_name || s.handle_or_url, platform: s.platform }))
      .filter((s) => !words || s.name.toLowerCase().includes(words))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [filter, sources.data]);
  const toggle = (id: string) => setPicked((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]));
  const make = async () => {
    setSaving(true);
    try {
      await voicesApi.join(picked, { name: name.trim() || undefined, byHand: true });
      toast.success('Made a voice');
      setOpen(false);
      setPicked([]);
      setName('');
      onDone();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>Make a voice</Button>
      <DialogContent title="Make a voice" description="Pick the channels of one person, company or publication.">
        <div className="flex flex-col gap-2">
          <Input aria-label="Voice name" placeholder="Name (its main channel's when empty)" value={name} onChange={(e) => setName(e.target.value)} />
          <Input aria-label="Filter sources" placeholder="Filter sources" value={filter} onChange={(e) => setFilter(e.target.value)} />
          {sources.isPending ? <LoadingState label="Loading sources" rows={3} /> : (
            <ul className="max-h-72 overflow-y-auto">
              {shown.map((s) => (
                <li key={s.id}>
                  <label className="flex min-w-0 items-baseline gap-2 py-1 text-[0.875rem]">
                    <input type="checkbox" checked={picked.includes(s.id)} onChange={() => toggle(s.id)} />
                    <span className="min-w-0 [overflow-wrap:anywhere]">{sourceLabel(s.name)}</span>
                    <span className="text-fg-3">{getPlatformLabel(s.platform)}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button disabled={picked.length < 2 || saving} onClick={() => void make()}>
            Join {plural(picked.length, 'source')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function VoiceRow({ voice, onChange }: { voice: Voice; onChange: () => void }) {
  const run = async (what: () => Promise<unknown>, done: string) => {
    try {
      await what();
      toast.success(done);
      onChange();
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };
  return (
    <li data-testid="voice-row" className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Link to={voiceReadPath(voice.id)} className="text-[0.9375rem] font-semibold text-fg underline decoration-transparent hover:decoration-fg-3 [overflow-wrap:anywhere]">
          {sourceLabel(voice.name)}
        </Link>
        <Button size="sm" variant="ghost" onClick={() => void run(() => voicesApi.remove(voice.id), 'Voice removed; its channels stay sources')}>
          Remove voice
        </Button>
      </div>
      <ul className="mt-1 flex flex-col gap-0.5">
        {voice.channels.map((c) => (
          <li key={c.id} className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-[0.8125rem] leading-5">
            <Link to={sourceReadPath(c.id)} className="min-w-0 text-fg [overflow-wrap:anywhere]">{sourceLabel(c.name)}</Link>
            <span className="text-fg-3">{getPlatformLabel(c.kind)} · {plural(c.posts, 'post')}{c.enabled ? '' : ' · off'}</span>
            <button type="button" className="text-fg-3 underline decoration-fg-3 hover:text-fg"
              onClick={() => void run(() => voicesApi.leave(c.id), `${sourceLabel(c.name)} left the voice`)}>leave</button>
          </li>
        ))}
      </ul>
      {voice.related.length ? (
        <p className="mt-1 text-[0.8125rem] leading-5 text-fg-3">Related: {voice.related.map((r) => sourceLabel(r.name)).join(', ')}</p>
      ) : null}
    </li>
  );
}

/** The Sources page's Voices tab (issue 0132 A): what is suggested, and the voices you made. */
export default function VoicesPanel({ onFollow }: { onFollow?: (url: string) => void } = {}) {
  const queryClient = useQueryClient();
  const voices = useQuery({ queryKey: [...VOICES_KEY, 'list'], queryFn: () => voicesApi.list() });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: VOICES_KEY });
  const many = (voices.data?.voices ?? []).filter((v) => v.channels.length > 1);
  return (
    <div className="flex flex-col gap-8">
      <SuggestedVoices onFollow={onFollow} />
      <section aria-labelledby="your-voices">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="your-voices" className="text-[1rem] font-semibold text-fg">Your voices</h2>
          <MakeVoice onDone={refresh} />
        </div>
        {voices.isPending ? <LoadingState label="Loading voices" rows={2} /> : voices.isError ? (
          <ErrorState error={voices.error} onRetry={() => void voices.refetch()} title="Could not load voices" />
        ) : many.length ? (
          <ul>{many.map((v) => <VoiceRow key={v.id} voice={v} onChange={refresh} />)}</ul>
        ) : (
          <p className="text-[0.8125rem] leading-5 text-fg-3">No voice yet. Join a suggestion, or make one by hand.</p>
        )}
      </section>
    </div>
  );
}
