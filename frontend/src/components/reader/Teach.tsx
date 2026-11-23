import { useState } from 'react';

import type { InterestAnswer, InterestTeach } from '../../services/api';
import { targetsOf, useTeach, type Target } from '../../hooks/useTeach';
import { errorMessage } from '../../lib/apiError';

type Direction = 'more' | 'less';

/**
 * "More" / "Less", then "because of": one chip a thing, the kind of news, the source; one tap each, and an Undo.
 * A chip already taught says so ("more" / "less").
 */
export function TeachPanel({ teach, row, post, onTaught }: {
  teach: InterestTeach; row?: string | null; post?: string | null; onTaught?: () => void;
}) {
  const [direction, setDirection] = useState<Direction | null>(null);
  const [last, setLast] = useState<{ target: Target; answer: InterestAnswer } | null>(null);
  const mutation = useTeach({ row, post }, onTaught);
  const targets = targetsOf(teach);
  const send = (target: Target, answer: InterestAnswer) => {
    mutation.mutate({ dim: target.dim, key: target.key, name: target.name, answer },
      { onSuccess: () => setLast(answer === 'undo' ? null : { target, answer }) });
  };
  if (!targets.length) return null;
  return (
    <div data-teach className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[0.8125rem] leading-5 text-fg-3">
      {(['more', 'less'] as const).map((d) => (
        <button key={d} type="button" aria-pressed={direction === d}
          className={`underline-offset-2 hover:underline ${direction === d ? 'font-semibold text-fg-1' : ''}`}
          onClick={() => setDirection(direction === d ? null : d)}>
          {d === 'more' ? 'More' : 'Less'}
        </button>
      ))}
      {direction ? (
        <span role="group" aria-label={`${direction === 'more' ? 'More' : 'Less'} because of`} className="contents">
          <span>because of:</span>
          {targets.map((t) => (
            <button key={`${t.dim}:${t.key}`} type="button" disabled={mutation.isPending}
              className="rounded border border-line px-1.5 text-fg-2 hover:text-fg-1"
              onClick={() => send(t, direction)}>
              {t.label}{t.answer === 'more' || t.answer === 'less' ? ` (${t.answer})` : ''}
            </button>
          ))}
        </span>
      ) : null}
      {last ? (
        <span role="status">
          {`Taught: ${last.answer} of ${last.target.name}. `}
          <button type="button" className="underline underline-offset-2 hover:text-fg-1" onClick={() => send(last.target, 'undo')}>
            Undo
          </button>
        </span>
      ) : null}
      {mutation.isError ? <span role="alert" className="text-fg">× {errorMessage(mutation.error)}</span> : null}
    </div>
  );
}
