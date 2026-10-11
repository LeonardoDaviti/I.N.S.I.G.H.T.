/**
 * Connections fixtures (tests, screenshots): the backend's write-only views
 * (`GET /api/credentials`). No fixture carries a secret value; only last4.
 */
import type { CredentialField, CredentialProviderView, CredentialsResponse } from '../../services/api';

export function field(overrides: Partial<CredentialField> & { key: string }): CredentialField {
  return {
    label: overrides.key,
    hint: '',
    writable: true,
    set: false,
    last4: null,
    updated_at: null,
    source: 'none',
    error: null,
    ...overrides,
  };
}

export function substackView(overrides: Partial<CredentialProviderView> = {}, sid: Partial<CredentialField> = {}): CredentialProviderView {
  const sidField = field({
    key: 'sid',
    label: 'Session cookie (substack.sid)',
    hint: 'Log into substack.com, open DevTools → Application → Cookies → substack.com and copy the value of substack.sid. It lasts months.',
    ...sid,
  });
  return {
    provider: 'substack',
    label: 'Substack',
    description: 'Full text of paid posts you subscribe to. Without it, paid posts arrive as teasers.',
    needed: true,
    testable: true,
    sign_in: false,
    configured: sidField.set,
    fields: [sidField],
    test: null,
    login: null,
    ...overrides,
  };
}

export function telegramView(
  { apiSet = false, session = false, ...overrides }: Partial<CredentialProviderView> & { apiSet?: boolean; session?: boolean } = {},
): CredentialProviderView {
  const fields = [
    field({ key: 'api_id', label: 'API ID', hint: 'The number shown at my.telegram.org → API development tools.', ...(apiSet ? { set: true, last4: '4821', source: 'db' as const, updated_at: '2026-10-09T10:00:00Z' } : {}) }),
    field({ key: 'api_hash', label: 'API hash', hint: 'The 32-character hash next to the API ID.', ...(apiSet ? { set: true, last4: '9e1c', source: 'db' as const, updated_at: '2026-10-09T10:00:00Z' } : {}) }),
    field({ key: 'session', label: 'Session', hint: 'Created by signing in with your phone number.', writable: false, ...(session ? { set: true, source: 'db' as const } : {}) }),
  ];
  return {
    provider: 'telegram',
    label: 'Telegram',
    description: 'Reads Telegram channels by handle. Create an app at my.telegram.org, then sign in.',
    needed: true,
    testable: true,
    sign_in: true,
    configured: fields.every((f) => f.set),
    fields,
    test: null,
    login: null,
    ...overrides,
  };
}

export function publicView(provider: 'reddit' | 'youtube'): CredentialProviderView {
  return {
    provider,
    label: provider === 'reddit' ? 'Reddit' : 'YouTube',
    description: 'Not needed: public feeds.',
    needed: false,
    testable: false,
    sign_in: false,
    configured: false,
    fields: [],
    test: null,
    login: null,
  };
}

export function credentials(...providers: CredentialProviderView[]): CredentialsResponse {
  return { providers };
}

/** The demo the screenshots use: substack working, telegram failing, reddit/youtube not needed. */
export function demoCredentials(now: Date = new Date()): CredentialsResponse {
  return credentials(
    substackView(
      { test: { ok: true, message: 'Read the newest paid post of The Kaitchup in full', tested_at: new Date(now.getTime() - 3_600_000).toISOString() } },
      { set: true, last4: 'a3f9', source: 'db', updated_at: '2026-10-10T08:00:00Z' },
    ),
    telegramView({ apiSet: true, session: true, test: { ok: false, message: 'The Telegram session is no longer authorised; sign in again', tested_at: new Date(now.getTime() - 600_000).toISOString() } }),
    publicView('reddit'),
    publicView('youtube'),
  );
}
