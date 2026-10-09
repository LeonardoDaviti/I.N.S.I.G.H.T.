import { useId, useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { SourceHealthRow } from '../../services/api';
import { replaceHealthRow } from '../../hooks/useSourcesHealth';
import { errorMessage } from '../../lib/apiError';
import { formatHours, intervalLabel, parseOverrideHours, tierLabel } from '../../lib/sourceSchedule';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';

/**
 * Edit one source's fetch interval override (spec §F.4): hours in [1, 2160], or
 * empty to go back to the cadence tier. Validation happens here, before the API
 * call; the server re-validates. Saves on submit and reports the fresh row.
 */
export default function CadenceOverrideEditor({
  row,
  onSaved,
  onCancel,
  className = '',
}: {
  row: SourceHealthRow;
  onSaved?: (row: SourceHealthRow) => void;
  onCancel?: () => void;
  className?: string;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const inputId = useId();
  const hintId = useId();
  const errorId = useId();
  const [text, setText] = useState(row.override_hours === null ? '' : String(row.override_hours));
  const [submitted, setSubmitted] = useState(false);

  const parsed = parseOverrideHours(text);
  const validationError = submitted && !parsed.ok ? parsed.error : null;

  const mutation = useMutation({
    mutationFn: (hours: number | null) => api.setCadenceOverride(row.source_id, hours),
    onSuccess: (response) => {
      // The PUT answers with the source's fresh row, so the cache is updated in place.
      replaceHealthRow(queryClient, response.row);
      onSaved?.(response.row);
    },
  });

  const save = (hours: number | null) => {
    mutation.mutate(hours);
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (parsed.ok) save(parsed.value);
  };

  const errorText = validationError ?? (mutation.error ? errorMessage(mutation.error) : null);
  const button = `inline-flex min-h-[44px] items-center justify-center rounded-lg px-3 text-sm font-medium disabled:opacity-60 ${PRESS_FEEDBACK} ${FOCUS_RING}`;
  const tierText = row.tier === 'unknown'
    ? 'probation (daily until 3 dated posts)'
    : `${tierLabel(row.tier).toLowerCase()} tier${row.mean_gap_hours !== null ? `, a post every ${formatHours(row.mean_gap_hours)} on average` : ''}`;

  return (
    <form onSubmit={onSubmit} noValidate className={`min-w-0 ${className}`} aria-label={`Cadence override for ${row.display_name}`}>
      <label htmlFor={inputId} className="block text-sm font-medium text-[var(--text-normal)]">
        Override (hours)
      </label>
      <p id={hintId} className="mt-0.5 text-xs text-[var(--text-muted)]">
        Now {intervalLabel(row)}; {tierText}. Leave empty to follow the tier. 1 to 2160 hours (90 days).
      </p>
      <div className="mt-2 flex flex-wrap items-start gap-2">
        <input
          id={inputId}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="tier"
          aria-invalid={validationError ? 'true' : 'false'}
          aria-describedby={`${hintId}${errorText ? ` ${errorId}` : ''}`}
          className={`min-h-[44px] w-28 rounded-lg border bg-[var(--background-primary)] px-3 text-sm tabular-nums text-[var(--text-normal)] ${FOCUS_RING} ${
            validationError ? 'border-[var(--text-error)]' : 'border-[var(--background-modifier-border)]'
          }`}
        />
        <button
          type="submit"
          disabled={mutation.isPending}
          className={`${button} bg-[var(--interactive-accent)] text-[var(--text-on-accent)] hover:bg-[var(--interactive-accent-hover)]`}
        >
          {mutation.isPending ? 'Saving…' : 'Save override'}
        </button>
        {row.override_hours !== null ? (
          <button
            type="button"
            disabled={mutation.isPending}
            onClick={() => { setText(''); setSubmitted(false); save(null); }}
            className={`${button} border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] text-[var(--text-normal)] hover:bg-[var(--background-secondary-alt)]`}
          >
            Use tier
          </button>
        ) : null}
        {onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className={`${button} text-[var(--text-muted)] hover:text-[var(--text-normal)]`}
          >
            Cancel
          </button>
        ) : null}
      </div>
      {errorText ? (
        <p id={errorId} role="alert" className="mt-1.5 break-words text-xs text-[var(--text-error)]">{errorText}</p>
      ) : null}
    </form>
  );
}
