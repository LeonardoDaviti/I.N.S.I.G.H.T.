import { useId, useState } from 'react';
import type { CredentialField } from '../../services/api';
import { Button, Input } from '../ui';
import { errorMessage } from '../../lib/apiError';
import { useApi } from '../../services/ApiContext';
import { fieldSummary } from './connectionStatus';
import { useReplaceProvider, useSaveCredential } from './useConnections';

/**
 * One secret, write-only: a password input until it is saved, then only
 * "set · ••••a3f · updated <date>" with replace and remove. The typed value is
 * dropped from state as soon as the save succeeds, so it is never rendered again.
 */
export default function ConnectionField({
  provider,
  field,
  placeholder,
  hideHint = false,
}: {
  provider: string;
  field: CredentialField;
  placeholder?: string;
  /** The provider shows its own how-to (Substack), so the hint would repeat it. */
  hideHint?: boolean;
}) {
  const id = useId();
  const api = useApi();
  const save = useSaveCredential();
  const replaceView = useReplaceProvider();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const showInput = field.writable && (!field.set || editing);
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  const submit = () => {
    const value = draft.trim();
    if (!value) return;
    setError(null);
    save.mutate({ provider, key: field.key, value }, {
      onSuccess: () => { setDraft(''); setEditing(false); },
      onError: (err) => setError(errorMessage(err)),
    });
  };

  const remove = async () => {
    setRemoving(true);
    setError(null);
    try {
      replaceView(await api.deleteCredential(provider, field.key));
      setConfirmRemove(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRemoving(false);
    }
  };

  return (
    <div className="space-y-1.5" data-field={field.key}>
      {showInput ? (
        <label htmlFor={id} className="block text-[0.8125rem] font-medium text-fg">{field.label}</label>
      ) : (
        <p id={`${id}-label`} className="text-[0.8125rem] font-medium text-fg">{field.label}</p>
      )}
      {showInput ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => { event.preventDefault(); submit(); }}
        >
          <Input
            id={id}
            type="password"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={placeholder ?? (field.set ? 'New value' : 'Paste the value')}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={[hideHint ? null : hintId, error ? errorId : null].filter(Boolean).join(' ') || undefined}
            aria-invalid={error ? true : undefined}
            className="min-w-[12rem] flex-1 font-mono"
            autoFocus={editing}
          />
          <Button type="submit" size="sm" variant="secondary" disabled={!draft.trim() || save.isPending} aria-busy={save.isPending || undefined}>
            {save.isPending ? 'saving…' : 'save'}
          </Button>
          {editing ? (
            <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setDraft(''); setError(null); }}>cancel</Button>
          ) : null}
        </form>
      ) : (
        <div role="group" aria-labelledby={`${id}-label`} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem]">
          <span className="font-mono tabular-nums text-fg-2 [overflow-wrap:anywhere]" data-testid="field-summary">
            {field.set ? fieldSummary(field) : 'not set'}
          </span>
          {field.writable ? (
            <span className="flex items-center gap-1">
              <Button size="sm" variant="ghost" onClick={() => { setEditing(true); setConfirmRemove(false); }}>replace</Button>
              {field.source === 'db' ? (
                confirmRemove ? (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => void remove()} disabled={removing}>
                      {removing ? 'removing…' : 'confirm remove'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(false)}>keep</Button>
                  </>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)}>remove</Button>
                )
              ) : null}
            </span>
          ) : null}
        </div>
      )}
      {hideHint ? null : <p id={hintId} className="text-[0.75rem] text-fg-3">{field.hint}</p>}
      {field.error ? <p className="text-[0.75rem] text-fg">{field.error}</p> : null}
      {error ? (
        <p id={errorId} role="alert" className="text-[0.75rem] text-fg [overflow-wrap:anywhere]">
          <span aria-hidden="true" className="mr-1 font-semibold">×</span>{error}
        </p>
      ) : null}
    </div>
  );
}
