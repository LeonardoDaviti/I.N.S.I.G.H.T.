// The voices' calls (issue 0132 A), beside createApi's: their own module, so only the voice pages' chunks load it.
import { request } from '../lib/request';
import type { Voice, VoiceEvidence, VoiceSuggestions } from './api';

const voicePath = (id: string) => `/api/voices/${encodeURIComponent(id)}`;

export const voicesApi = {
  list: () => request<{ success: true; voices: Voice[] }>('/api/voices'),
  get: (id: string) => request<{ success: true; voice: Voice }>(voicePath(id)),
  ofSource: (sourceId: string) =>
    request<{ success: true; voice: Voice | null }>(`/api/sources/${encodeURIComponent(sourceId)}/voice`),
  suggestions: () => request<VoiceSuggestions>('/api/voices/suggestions'),
  refresh: () => request<{ success: true; started: boolean }>('/api/voices/suggestions/refresh', { method: 'POST', body: {} }),
  /** Join (a suggestion, with its evidence) or Make a voice (`byHand`); `voiceId` adds them to that voice. */
  join: (sourceIds: string[], opts: { voiceId?: string; name?: string; evidence?: VoiceEvidence[]; byHand?: boolean } = {}) =>
    request<{ success: true; voice: Voice; queued_sources: string[] }>('/api/voices', {
      method: 'POST',
      body: { source_ids: sourceIds, voice_id: opts.voiceId, name: opts.name, evidence: opts.evidence, by_hand: Boolean(opts.byHand) },
    }),
  notSame: (a: string, b: string, evidence?: VoiceEvidence[]) =>
    request<{ success: true }>('/api/voices/not-same', { method: 'POST', body: { a, b, evidence } }),
  related: (a: string, b: string, evidence?: VoiceEvidence[]) =>
    request<{ success: true; voices: Voice[] }>('/api/voices/related', { method: 'POST', body: { a, b, evidence } }),
  leave: (sourceId: string) => request<{ success: true }>('/api/voices/leave', { method: 'POST', body: { source_id: sourceId } }),
  rename: (id: string, name: string) => request<{ success: true; voice: Voice }>(voicePath(id), { method: 'PUT', body: { name } }),
  remove: (id: string) => request<{ success: true; source_ids: string[] }>(voicePath(id), { method: 'DELETE' }),
};
