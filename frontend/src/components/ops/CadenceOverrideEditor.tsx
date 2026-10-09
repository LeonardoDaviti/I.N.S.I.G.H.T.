import { useId, useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { SourceHealthRow } from '../../services/api';
import { replaceHealthRow } from '../../hooks/useSourcesHealth';
import { errorMessage } from '../../lib/apiError';
import { formatHours, intervalLabel, parseOverrideHours, tierLabel } from '../../lib/sourceSchedule';
import { Button, Input } from '../ui';

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
  const tierText = row.tier === 'unknown'
    ? 'probation (daily until 3 dated posts)'
    : `${tierLabel(row.tier).toLowerCase()} tier${row.mean_gap_hours !== null ? `, a post every ${formatHours(row.mean_gap_hours)} on average` : ''}`;

  return (
    <form onSubmit={onSubmit} noValidate className={`min-w-0 ${className}`} aria-label={`Cadence override for ${row.display_name}`}>
      <label htmlFor={inputId} className="block text-[0.8125rem] font-medium text-fg">
        Override (hours)
      </label>
      <p id={hintId} className="mt-0.5 text-[0.75rem] text-fg-2">
        Now {intervalLabel(row)}; {tierText}. Leave empty to follow the tier. 1 to 2160 hours (90 days).
      </p>
      <div className="mt-2 flex flex-wrap items-start gap-2">
        <Input
          id={inputId}
          inputMode="decimal"
          autoComplete="off"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="tier"
          aria-invalid={validationError ? 'true' : 'false'}
          aria-describedby={`${hintId}${errorText ? ` ${errorId}` : ''}`}
          className="w-28 tabular-nums"
        />
        <Button type="submit" variant="secondary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving…' : 'Save override'}
        </Button>
        {row.override_hours !== null ? (
          <Button variant="secondary" disabled={mutation.isPending} onClick={() => { setText(''); setSubmitted(false); save(null); }}>
            Use tier
          </Button>
        ) : null}
        {onCancel ? (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
      {errorText ? (
        <p id={errorId} role="alert" className="mt-1.5 break-words text-[0.75rem] font-semibold text-fg"><span aria-hidden="true">× </span>{errorText}</p>
      ) : null}
    </form>
  );
}
