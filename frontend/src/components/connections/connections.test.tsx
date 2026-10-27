import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import ConnectionsPanel from './ConnectionsPanel';
import ConnectionsLink from './ConnectionsLink';
import AddSourceModal from '../AddSourceModal';
import { credentials, demoCredentials, substackView, telegramView } from './fixtures';
import { cookieValue, isSubstackUrl, missingCredentialProvider, providerStatus } from './connectionStatus';
import { healthRow } from '../ops/fixtures';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { ApiError } from '../../lib/apiError';
import type { Api } from '../../services/api';

const SECRET = 's%3AQx7Lw9ZpRk2vBn4Tj8Hc1Ym6.a3f9';
const savedSubstack = () => substackView({}, { set: true, last4: 'a3f9', source: 'db', updated_at: '2026-10-10T08:00:00Z' });

function setup(methods: Partial<Record<keyof Api, unknown>>, initialOpen?: string) {
  return renderWithProviders(<ConnectionsPanel initialOpen={initialOpen} />, { api: makeFakeApi(methods) });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe('providerStatus', () => {
  it('names each state with a glyph and a word', () => {
    expect(providerStatus(substackView())).toMatchObject({ glyph: 'scheduled', label: 'not set' });
    expect(providerStatus(savedSubstack())).toMatchObject({ glyph: 'ok', label: 'set · not tested' });
    expect(providerStatus({ ...savedSubstack(), test: { ok: true, message: 'ok', tested_at: null } })).toMatchObject({ label: 'working' });
    expect(providerStatus({ ...savedSubstack(), test: { ok: false, message: 'Substack session expired', tested_at: null } }))
      .toEqual({ glyph: 'failing', label: 'failing', message: 'Substack session expired' });
    expect(providerStatus(telegramView({ apiSet: true }))).toMatchObject({ label: 'sign in needed' });
  });

  it('helpers: substack URLs, cookie pairs, the provider a health row needs', () => {
    expect(isSubstackUrl('https://kaitchup.substack.com/')).toBe(true);
    expect(isSubstackUrl('kaitchup.substack.com/feed')).toBe(true);
    expect(isSubstackUrl('https://notsubstack.com')).toBe(false);
    expect(isSubstackUrl('https://substack.com.evil.example')).toBe(false);
    expect(cookieValue('substack.sid=abc ')).toBe('abc');
    expect(missingCredentialProvider(healthRow({ platform: 'telegram', kind: 'telegram_mtproto', status: 'unavailable', unavailable_reason: 'no Telegram session at /app/x; sign in under Sources → Connections' }))).toBe('telegram');
    expect(missingCredentialProvider(healthRow({ kind: 'substack', credential_notice: 'Paid posts arrive as teasers. Add your Substack session in Sources → Connections' }))).toBe('substack');
    expect(missingCredentialProvider(healthRow({ status: 'unavailable', decision_detail: 'yt-dlp is off' }))).toBeNull();
  });
});

describe('ConnectionsPanel', () => {
  it('lists one row per provider with its status', async () => {
    setup({ getCredentials: vi.fn().mockResolvedValue(demoCredentials()) });
    await screen.findByText('Substack');
    const row = (p: string) => document.querySelector<HTMLElement>(`li[data-provider="${p}"]`)!;
    expect(row('substack')).toHaveTextContent('working');
    expect(row('telegram')).toHaveTextContent('failing');
    expect(row('telegram')).toHaveTextContent('no longer authorised');
    // Reddit and YouTube read public feeds: no row, rather than one saying so twice (issue 0027).
    expect(document.querySelectorAll('li[data-provider]')).toHaveLength(2);
  });

  it('is write-only: the saved value is never rendered, only set · ••••last4 · updated', async () => {
    const putCredential = vi.fn().mockResolvedValue(savedSubstack());
    const deleteCredential = vi.fn().mockResolvedValue(substackView());
    setup({ getCredentials: vi.fn().mockResolvedValue(credentials(substackView())), putCredential, deleteCredential }, 'substack');

    const input = await screen.findByLabelText('Session cookie (substack.sid)');
    expect(input).toHaveAttribute('type', 'password');
    expect(screen.getByText(/Open DevTools → Application → Cookies/)).toBeInTheDocument();
    expect(screen.getByText(/personal use of your own subscription/)).toBeInTheDocument();

    await userEvent.type(input, SECRET);
    await userEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() => expect(putCredential).toHaveBeenCalledWith('substack', 'sid', SECRET));

    expect(await screen.findByTestId('field-summary')).toHaveTextContent('set · ••••a3f9 · updated 2026-10-10');
    expect(document.body.textContent).not.toContain(SECRET);
    expect([...document.querySelectorAll('input')].map((i) => i.value)).not.toContain(SECRET);

    // replace opens an empty input; cancel goes back to the summary
    await userEvent.click(screen.getByRole('button', { name: 'replace' }));
    expect(screen.getByLabelText('Session cookie (substack.sid)')).toHaveValue('');
    await userEvent.click(screen.getByRole('button', { name: 'cancel' }));

    await userEvent.click(screen.getByRole('button', { name: 'remove' }));
    await userEvent.click(screen.getByRole('button', { name: 'confirm remove' }));
    await waitFor(() => expect(deleteCredential).toHaveBeenCalledWith('substack', 'sid'));
    expect(await screen.findByLabelText('Session cookie (substack.sid)')).toHaveValue('');
  });

  it('a rejected save shows the server message and keeps nothing on screen but the input', async () => {
    const putCredential = vi.fn().mockRejectedValue(new ApiError(400, 'That does not look like a substack.sid cookie'));
    setup({ getCredentials: vi.fn().mockResolvedValue(credentials(substackView())), putCredential }, 'substack');
    await userEvent.type(await screen.findByLabelText('Session cookie (substack.sid)'), 'nope nope');
    await userEvent.click(screen.getByRole('button', { name: 'save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That does not look like a substack.sid cookie');
    expect(screen.getByLabelText('Session cookie (substack.sid)')).toHaveAttribute('aria-invalid', 'true');
  });

  it('a field is either set (stored, with remove) or not set; nothing mentions .env', async () => {
    setup({ getCredentials: vi.fn().mockResolvedValue(credentials(savedSubstack(), telegramView())) }, 'substack');
    expect(await screen.findByTestId('field-summary')).toHaveTextContent('set · ••••a3f9 · updated 2026-10-10');
    expect(screen.getByRole('button', { name: 'remove' })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/\.env/);
  });

  it('test: disabled with nothing set, testing… while running, then the inline result', async () => {
    const { unmount } = setup({ getCredentials: vi.fn().mockResolvedValue(credentials(substackView())) }, 'substack');
    expect(await screen.findByRole('button', { name: 'test' })).toBeDisabled();
    unmount();

    const pending = deferred<ReturnType<typeof savedSubstack>>();
    const testCredential = vi.fn().mockReturnValueOnce(pending.promise).mockRejectedValueOnce(new ApiError(500, 'The backend hit an internal error'));
    setup({ getCredentials: vi.fn().mockResolvedValue(credentials(savedSubstack())), testCredential }, 'substack');
    await userEvent.click(await screen.findByRole('button', { name: 'test' }));
    const busy = screen.getByRole('button', { name: 'testing…' });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute('aria-busy', 'true');

    pending.resolve({ ...savedSubstack(), test: { ok: false, message: 'Substack session expired — update it in Sources → Connections', tested_at: new Date().toISOString() } });
    const result = await screen.findByTestId('test-result');
    expect(result).toHaveTextContent('failed');
    expect(result).toHaveTextContent('Substack session expired');
    expect(result).toHaveTextContent('just now');
    expect(document.querySelector('li[data-provider="substack"]')).toHaveTextContent('failing');

    await userEvent.click(screen.getByRole('button', { name: 'test' }));
    expect(await screen.findByTestId('test-result')).toHaveTextContent('Could not run the test: The backend hit an internal error');
  });

  it('telegram: sign in needs the API values first', async () => {
    setup({ getCredentials: vi.fn().mockResolvedValue(credentials(telegramView())) }, 'telegram');
    expect(await screen.findByText(/Save the API ID and hash, then sign in/)).toBeInTheDocument();
    expect(screen.getByLabelText('API ID')).toHaveAttribute('type', 'password');
    expect(screen.getByLabelText('API hash')).toHaveAttribute('type', 'password');
    expect(screen.queryByRole('button', { name: 'sign in' })).not.toBeInTheDocument();
  });

  it('telegram wizard: phone → code → 2FA password → signed in as <name>', async () => {
    const getCredentials = vi.fn()
      .mockResolvedValueOnce(credentials(telegramView({ apiSet: true })))
      .mockResolvedValue(credentials(telegramView({ apiSet: true, session: true, test: { ok: true, message: 'Signed in as @owner', tested_at: new Date().toISOString() } })));
    const telegramLoginStart = vi.fn().mockResolvedValue({ stage: 'code' });
    const telegramLoginCode = vi.fn()
      .mockRejectedValueOnce(new ApiError(400, 'Wrong code; try again'))
      .mockResolvedValueOnce({ stage: 'password' });
    const telegramLoginPassword = vi.fn().mockResolvedValue({ stage: 'done', account: '@owner' });
    setup({ getCredentials, telegramLoginStart, telegramLoginCode, telegramLoginPassword }, 'telegram');

    expect(await screen.findByRole('button', { name: 'sign in' })).toBeInTheDocument();
    expect(document.querySelector('li[data-provider="telegram"]')).toHaveTextContent('sign in needed');
    await userEvent.click(screen.getByRole('button', { name: 'sign in' }));

    const wizard = screen.getByRole('form', { name: 'Telegram sign-in' });
    await userEvent.type(within(wizard).getByLabelText('Phone number'), '+15551234567');
    await userEvent.click(within(wizard).getByRole('button', { name: 'send code' }));
    expect(telegramLoginStart).toHaveBeenCalledWith('+15551234567');

    const code = await within(wizard).findByLabelText('Login code');
    await userEvent.type(code, '11111');
    await userEvent.click(within(wizard).getByRole('button', { name: 'sign in' }));
    expect(await within(wizard).findByRole('alert')).toHaveTextContent('Wrong code; try again');
    await userEvent.clear(within(wizard).getByLabelText('Login code'));
    await userEvent.type(within(wizard).getByLabelText('Login code'), '12345');
    await userEvent.click(within(wizard).getByRole('button', { name: 'sign in' }));
    expect(telegramLoginCode).toHaveBeenLastCalledWith('12345');

    const password = await within(wizard).findByLabelText('Two-step verification password');
    expect(password).toHaveAttribute('type', 'password');
    await userEvent.type(password, 'correct horse');
    await userEvent.click(within(wizard).getByRole('button', { name: 'sign in' }));
    expect(telegramLoginPassword).toHaveBeenCalledWith('correct horse');

    expect(await screen.findByText('signed in as @owner')).toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'Telegram sign-in' })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('correct horse');
    await waitFor(() => expect(document.querySelector('li[data-provider="telegram"]')).toHaveTextContent('working'));
  });

  it('telegram wizard resumes a pending sign-in and cancel ends it', async () => {
    const telegramLoginCancel = vi.fn().mockResolvedValue({ stage: null });
    setup({ getCredentials: vi.fn().mockResolvedValue(credentials(telegramView({ apiSet: true, login: { stage: 'code' } }))), telegramLoginCancel }, 'telegram');
    expect(await screen.findByLabelText('Login code')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'cancel' }));
    expect(telegramLoginCancel).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'sign in' })).toBeInTheDocument();
  });

  it('shows signed in as <name> from the last test', async () => {
    setup({ getCredentials: vi.fn().mockResolvedValue(credentials(telegramView({ apiSet: true, session: true, test: { ok: true, message: 'Signed in as @owner', tested_at: null } }))) }, 'telegram');
    expect(await screen.findByText('signed in as @owner')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'sign in again' })).toBeInTheDocument();
  });
});

describe('ConnectionsLink', () => {
  it('links an unavailable telegram source to its connection; nothing for other reasons', () => {
    const api = makeFakeApi({});
    const { unmount } = renderWithProviders(
      <ConnectionsLink row={healthRow({ platform: 'telegram', kind: 'telegram_mtproto', status: 'unavailable', unavailable_reason: 'Telegram API ID is not set; add it in Sources → Connections' })} />,
      { api },
    );
    expect(screen.getByRole('link', { name: 'add in Connections' })).toHaveAttribute('href', '/settings/sources?tab=connections&provider=telegram');
    unmount();
    renderWithProviders(<ConnectionsLink row={healthRow({ kind: 'substack', credential_notice: 'Paid posts arrive as teasers. Add your Substack session in Sources → Connections' })} />, { api });
    expect(screen.getByText('Paid posts arrive as teasers.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'add in Connections' })).toHaveAttribute('href', '/settings/sources?tab=connections&provider=substack');
  });
});

describe('AddSourceModal: Substack', () => {
  function renderModal(methods: Partial<Record<keyof Api, unknown>>) {
    const onAdd = vi.fn();
    const onClose = vi.fn();
    // A Substack address is read directly: the feed finder leaves it as typed.
    const findFeed = vi.fn().mockResolvedValue({ success: true, status: 'direct', feeds: [] });
    renderWithProviders(<AddSourceModal onAdd={onAdd} onClose={onClose} />, { api: makeFakeApi({ findFeed, ...methods }) });
    return { onAdd, onClose };
  }
  const addWhenReady = async () => {
    const add = screen.getByRole('button', { name: 'Add source' });
    await waitFor(() => expect(add).toBeEnabled());
    await userEvent.click(add);
  };

  it('offers the optional substack.sid only for a Substack URL and saves it to Connections', async () => {
    const putCredential = vi.fn().mockResolvedValue(savedSubstack());
    const { onAdd } = renderModal({ getCredentials: vi.fn().mockResolvedValue(credentials(substackView())), putCredential });
    const url = screen.getByLabelText('Feed URL or handle');
    await userEvent.type(url, 'https://example.com/feed.xml');
    expect(screen.queryByTestId('substack-sid')).not.toBeInTheDocument();

    await userEvent.clear(url);
    await userEvent.type(url, 'https://kaitchup.substack.com/');
    const sid = await screen.findByLabelText(/Paid subscription\? Add your substack.sid/);
    expect(sid).toHaveAttribute('type', 'password');
    expect(screen.getByTestId('substack-sid')).toHaveTextContent('DevTools → Application → Cookies');
    await userEvent.type(sid, `substack.sid=${SECRET}`);
    await addWhenReady();

    await waitFor(() => expect(putCredential).toHaveBeenCalledWith('substack', 'sid', SECRET));
    await waitFor(() => expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ handle_or_url: 'https://kaitchup.substack.com/' })));
  });

  it('adds without a cookie (teasers) and keeps the dialog open when the cookie is rejected', async () => {
    const putCredential = vi.fn().mockRejectedValue(new ApiError(400, 'That does not look like a substack.sid cookie'));
    const { onAdd } = renderModal({ getCredentials: vi.fn().mockResolvedValue(credentials(substackView())), putCredential });
    await userEvent.type(screen.getByLabelText('Feed URL or handle'), 'https://kaitchup.substack.com/');
    await userEvent.type(await screen.findByLabelText(/Paid subscription/), 'bad value');
    await addWhenReady();
    expect(await screen.findByRole('alert')).toHaveTextContent('That does not look like a substack.sid cookie');
    expect(onAdd).not.toHaveBeenCalled();

    await userEvent.clear(screen.getByLabelText(/Paid subscription/));
    await userEvent.click(screen.getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    expect(putCredential).toHaveBeenCalledTimes(1);
  });

  it('says the session is already set when Connections has it', async () => {
    renderModal({ getCredentials: vi.fn().mockResolvedValue(credentials(savedSubstack())) });
    await userEvent.type(screen.getByLabelText('Feed URL or handle'), 'https://kaitchup.substack.com/');
    expect(await screen.findByText(/your Substack session is set in Connections/)).toHaveTextContent('••••a3f9');
    expect(screen.queryByLabelText(/Paid subscription/)).not.toBeInTheDocument();
  });
});
