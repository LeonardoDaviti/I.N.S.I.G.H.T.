import { useId, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { CredentialProviderView, TelegramLoginStep } from '../../services/api';
import { useApi } from '../../services/ApiContext';
import { Button, Input, StatusGlyph } from '../ui';
import { errorMessage } from '../../lib/apiError';
import { SOURCES_HEALTH_KEY } from '../../hooks/useSourcesHealth';
import { CREDENTIALS_KEY } from './useConnections';

type Stage = 'idle' | 'phone' | 'code' | 'password' | 'done';

/** "Signed in as @user" (the stored test) → "@user". */
function accountFromTest(view: CredentialProviderView): string | null {
  const message = view.test?.ok ? view.test.message : '';
  const match = /^Signed in as (.+)$/.exec(message ?? '');
  return match ? match[1] : null;
}

/**
 * Telegram's browser sign-in, inline: phone → code → (two-step password when the
 * account has one) → "signed in as <name>". Needs the API ID and hash first.
 * A sign-in the backend still holds (10 minutes) resumes at its step.
 */
export default function TelegramSignIn({ view }: { view: CredentialProviderView }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const id = useId();
  const session = view.fields.find((f) => f.key === 'session');
  const ready = view.fields.filter((f) => f.key !== 'session').every((f) => f.set);
  const resumed = view.login?.stage === 'code' || view.login?.stage === 'password' ? view.login.stage : null;
  const [stage, setStage] = useState<Stage>(resumed ?? 'idle');
  const [value, setValue] = useState('');
  const [account, setAccount] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: [...CREDENTIALS_KEY] });
    void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
  };

  const step = async (call: () => Promise<TelegramLoginStep>) => {
    setBusy(true);
    setError(null);
    try {
      const next = await call();
      setValue('');
      if (next.stage === 'done') {
        setAccount(next.account);
        setStage('done');
        refresh();
      } else {
        setStage(next.stage);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setStage('idle');
    setValue('');
    setError(null);
    try { await api.telegramLoginCancel(); } catch { /* the pending sign-in expires on its own */ }
  };

  if (!ready) {
    return <p className="text-[0.8125rem] text-fg-3">Save the API ID and hash, then sign in with your phone number.</p>;
  }

  const signedInAs = account ?? accountFromTest(view);
  if (stage === 'idle' || stage === 'done') {
    const signedIn = stage === 'done' || session?.set;
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[0.8125rem]" aria-live="polite">
        {signedIn ? (
          <StatusGlyph status="ok" label={signedInAs ? `signed in as ${signedInAs}` : 'signed in'} />
        ) : (
          <span className="text-fg-2">Not signed in.</span>
        )}
        <Button size="sm" variant={signedIn ? 'ghost' : 'secondary'} onClick={() => { setStage('phone'); setAccount(null); }}>
          {signedIn ? 'sign in again' : 'sign in'}
        </Button>
      </div>
    );
  }

  const steps: Record<'phone' | 'code' | 'password', { label: string; hint: string; submit: string; input: ReactNode; call: () => Promise<TelegramLoginStep> }> = {
    phone: {
      label: 'Phone number',
      hint: 'International format, e.g. +15551234567. Telegram sends a code to your app.',
      submit: 'send code',
      input: <Input id={id} type="tel" inputMode="tel" autoComplete="tel" value={value} onChange={(e) => setValue(e.target.value)} placeholder="+15551234567" autoFocus className="tabular-nums" />,
      call: () => api.telegramLoginStart(value.trim()),
    },
    code: {
      label: 'Login code',
      hint: 'The code Telegram just sent to your Telegram app.',
      submit: 'sign in',
      input: <Input id={id} inputMode="numeric" autoComplete="one-time-code" value={value} onChange={(e) => setValue(e.target.value)} placeholder="12345" autoFocus className="tabular-nums" />,
      call: () => api.telegramLoginCode(value.trim()),
    },
    password: {
      label: 'Two-step verification password',
      hint: 'Your account has a cloud password. It is used once to sign in and not stored.',
      submit: 'sign in',
      input: <Input id={id} type="password" autoComplete="current-password" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />,
      call: () => api.telegramLoginPassword(value),
    },
  };
  const current = steps[stage];
  const order = ['phone', 'code', 'password'] as const;

  return (
    <form
      aria-label="Telegram sign-in"
      className="space-y-2 rounded-md border border-line p-3"
      onSubmit={(event) => { event.preventDefault(); if (value.trim()) void step(current.call); }}
    >
      <p className="text-[0.75rem] tabular-nums text-fg-3">
        step {order.indexOf(stage) + 1} of {view.login?.stage === 'password' || stage === 'password' ? 3 : 2}
      </p>
      <label htmlFor={id} className="block text-[0.8125rem] font-medium text-fg">{current.label}</label>
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-[12rem] flex-1">{current.input}</div>
        <Button type="submit" size="sm" variant="primary" disabled={!value.trim() || busy} aria-busy={busy || undefined}>
          {busy ? 'checking…' : current.submit}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void cancel()} disabled={busy}>cancel</Button>
      </div>
      <p className="text-[0.75rem] text-fg-3">{current.hint}</p>
      {error ? (
        <p role="alert" className="text-[0.75rem] text-fg [overflow-wrap:anywhere]">
          <span aria-hidden="true" className="mr-1 font-semibold">×</span>{error}
        </p>
      ) : null}
    </form>
  );
}
