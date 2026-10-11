import type { CredentialField, CredentialProviderView, SourceHealthRow } from '../../services/api';
import type { Status } from '../ui/styles';
import { localDateISO } from '../../lib/dates';

/** The Connections tab's URL (spec §10.1); one place so every link agrees. */
export const CONNECTIONS_PATH = '/settings/sources?tab=connections';

export function connectionsHref(provider?: string): string {
  return provider ? `${CONNECTIONS_PATH}&provider=${encodeURIComponent(provider)}` : CONNECTIONS_PATH;
}

export interface ProviderStatus {
  glyph: Status;
  label: string;
  /** The failing message, shown next to the glyph. */
  message?: string;
}

/**
 * One provider's state as a glyph and a word (monochrome, design docs system/status.md):
 * working (tested ok), failing (last test failed, or a saved value cannot be read),
 * set (all fields set, not tested yet), not set, not needed.
 */
export function providerStatus(view: CredentialProviderView): ProviderStatus {
  if (!view.needed) return { glyph: 'disabled', label: 'not needed' };
  const broken = view.fields.find((f) => f.error);
  if (broken) return { glyph: 'failing', label: 'failing', message: broken.error ?? undefined };
  if (view.test && !view.test.ok) return { glyph: 'failing', label: 'failing', message: view.test.message };
  if (view.configured) {
    return view.test?.ok ? { glyph: 'ok', label: 'working' } : { glyph: 'ok', label: 'set · not tested' };
  }
  if (view.fields.some((f) => f.set)) {
    const session = view.fields.find((f) => f.key === 'session');
    const onlySessionMissing = session && !session.set && view.fields.every((f) => f.set || f.key === 'session');
    return { glyph: 'scheduled', label: onlySessionMissing ? 'sign in needed' : 'incomplete' };
  }
  return { glyph: 'scheduled', label: 'not set' };
}

/** "set · ••••a3f · updated 2026-10-10". Never the value: only its last 4. */
export function fieldSummary(field: CredentialField): string {
  const parts = ['set'];
  if (field.last4) parts.push(`••••${field.last4}`);
  if (field.updated_at) {
    const date = new Date(field.updated_at);
    if (!Number.isNaN(date.getTime())) parts.push(`updated ${localDateISO(date)}`);
  }
  return parts.join(' · ');
}

/** True for https://name.substack.com/… and substack.com URLs (the substack kind's own test). */
export function isSubstackUrl(value: string): boolean {
  const text = value.trim();
  if (!text) return false;
  try {
    const host = new URL(/^[a-z]+:\/\//i.test(text) ? text : `https://${text}`).hostname.toLowerCase();
    return host === 'substack.com' || host.endsWith('.substack.com');
  } catch {
    return false;
  }
}

/** "substack.sid=abc" pasted from a cookie header: keep the value only (as the backend does). */
export function cookieValue(raw: string): string {
  const text = raw.trim();
  return text.startsWith('substack.sid=') ? text.slice('substack.sid='.length).trim() : text;
}

/** Which provider a health row needs, when it is unavailable (or degraded) for a missing credential. */
export function missingCredentialProvider(row: Pick<SourceHealthRow, 'status' | 'kind' | 'platform' | 'decision_detail' | 'unavailable_reason' | 'credential_notice'>): string | null {
  const reason = [row.unavailable_reason, row.status === 'unavailable' ? row.decision_detail : null, row.credential_notice]
    .filter(Boolean)
    .join(' ');
  if (!/Connections/.test(reason)) return null;
  const kind = `${row.kind} ${row.platform}`.toLowerCase();
  if (kind.includes('substack') || /substack/i.test(reason)) return 'substack';
  if (kind.includes('telegram') || /telegram/i.test(reason)) return 'telegram';
  return null;
}
