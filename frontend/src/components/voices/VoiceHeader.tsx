import { useState, type FormEvent } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import type { Voice } from '../../services/api';
import { voicesApi } from '../../services/voices';
import { Button, Input, tabTriggerClass } from '../ui';
import { sourceReadPath, voiceReadPath } from '../../lib/feedContext';
import { getPlatformLabel, sourceLabel } from '../../lib/sourceLabel';
import { errorMessage } from '../../lib/apiError';
import { VOICES_KEY } from '../../hooks/useVoice';
import NotFollowed from './NotFollowed';

/** The view a tab keeps (News, Classics): a channel's tab reads the same view of that channel. */
function keptSearch(search: string): string {
  const view = new URLSearchParams(search).get('view');
  return view === 'news' || view === 'classics' ? `?view=${view}` : '';
}

/** 0132 C2: the voice's other channels you don't follow, each with Add (the feed finder, prefilled). */
function VoiceNotFollowed({ id }: { id: string }) {
  const query = useQuery({ queryKey: [...VOICES_KEY, 'not-followed', id], queryFn: () => voicesApi.get(id), staleTime: 60_000, retry: false });
  const channels = query.data?.not_followed ?? [];
  return channels.length ? <div className="w-full"><NotFollowed channels={channels} /></div> : null;
}

/**
 * A voice's header on the reader (issue 0132 A): one tab for every channel together and one per channel (a single
 * channel can still be read alone), on the voice's page and on each channel's. The voice's page renames it (its
 * name is its main channel's until you do) and names its related voices.
 */
export default function VoiceHeader({ scope, voice }: { scope: string; voice: Voice }) {
  const location = useLocation();
  const queryClient = useQueryClient();
  const search = keptSearch(location.search);
  const onVoice = scope === `voice:${voice.id}`;
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(voice.name);
  const [saving, setSaving] = useState(false);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || name.trim() === voice.name) {
      setRenaming(false);
      return;
    }
    setSaving(true);
    try {
      await voicesApi.rename(voice.id, name.trim());
      await queryClient.invalidateQueries({ queryKey: VOICES_KEY });
      setRenaming(false);
    } catch (error) {
      toast.error(`Could not rename the voice: ${errorMessage(error)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section aria-label="Voice" data-testid="voice-header" className="mb-3 border-b border-line">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-1">
        {onVoice ? (
          renaming ? (
            <form onSubmit={save} className="flex min-w-0 flex-1 items-center gap-2">
              <Input aria-label="Voice name" value={name} onChange={(e) => setName(e.target.value)} className="min-w-0 flex-1" autoFocus />
              <Button type="submit" size="sm" disabled={saving}>Save</Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => { setName(voice.name); setRenaming(false); }}>Cancel</Button>
            </form>
          ) : (
            <p className="text-[0.8125rem] leading-5 text-fg-2">
              One voice, {voice.channels.length} channels{' '}
              <button type="button" onClick={() => setRenaming(true)} className="underline decoration-fg-3 hover:text-fg">Rename</button>
            </p>
          )
        ) : (
          <p className="text-[0.8125rem] leading-5 text-fg-2">
            A channel of <Link to={`${voiceReadPath(voice.id)}${search}`} className="text-fg underline decoration-fg-3">{sourceLabel(voice.name)}</Link>
          </p>
        )}
        {onVoice ? <VoiceNotFollowed id={voice.id} /> : null}
        {voice.related.length ? (
          <p className="text-[0.8125rem] leading-5 text-fg-3">
            Related: {voice.related.map((r, i) => (
              <span key={r.id}>{i ? ', ' : ''}<Link to={voiceReadPath(r.id)} className="underline decoration-transparent hover:decoration-fg-3">{sourceLabel(r.name)}</Link></span>
            ))} (needs a bio)
          </p>
        ) : null}
      </div>
      <nav aria-label="Channels" className="-mb-px flex gap-4 overflow-x-auto px-1">
        <Link to={`${voiceReadPath(voice.id)}${search}`} aria-current={onVoice ? 'page' : undefined} className={tabTriggerClass}>
          all channels
        </Link>
        {voice.channels.map((channel) => (
          <Link
            key={channel.id}
            to={`${sourceReadPath(channel.id)}${search}`}
            aria-current={scope === `source:${channel.id}` ? 'page' : undefined}
            className={tabTriggerClass}
            title={`${sourceLabel(channel.name)} · ${getPlatformLabel(channel.kind)}${channel.enabled ? '' : ' · off'}`}
          >
            {sourceLabel(channel.name)}
            <span className="text-fg-3">{getPlatformLabel(channel.kind)}</span>
          </Link>
        ))}
      </nav>
    </section>
  );
}
