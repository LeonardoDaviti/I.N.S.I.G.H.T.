import { useState } from 'react';

import type { NewsPersonal } from '../../services/api';
import { useTeach } from '../../hooks/useTeach';
import { TeachPanel } from './Teach';

/**
 * v10.42: a News row's "for you" line: the largest reason your interest moved it ("you follow Inkling 2 Small",
 * "you lowered 'releases for someone else's model'"), "Not why" to correct that reason (a tap of yours: taken back; a
 * learned one: not a reason any more), and "Teach" to say More or Less of one of its things, its kind or its source.
 */
export default function ForYou({ personal, row, post }: { personal: NewsPersonal; row: string; post: string }) {
  const [open, setOpen] = useState(false);
  const top = personal.reasons.find((r) => !r.beaten) ?? null;
  const correct = useTeach({ row, post });
  return (
    <div data-for-you className="mt-0.5 max-sm:col-start-1 text-[0.8125rem] leading-5 text-fg-3">
      <p className="flex flex-wrap items-baseline gap-x-2">
        {personal.why && top ? (
          <>
            <span><span className="font-semibold">For you</span>{` · ${personal.why}`}</span>
            <button type="button" className="underline-offset-2 hover:underline hover:text-fg-1" disabled={correct.isPending}
              onClick={() => correct.mutate({ dim: top.dim, key: top.key, name: top.name,
                answer: top.by === 'learned' ? 'none' : 'undo' })}>
              Not why
            </button>
          </>
        ) : null}
        <button type="button" aria-expanded={open} className="underline-offset-2 hover:underline hover:text-fg-1"
          onClick={() => setOpen(!open)}>
          Teach
        </button>
      </p>
      {open ? <TeachPanel teach={personal.teach} row={row} post={post} /> : null}
    </div>
  );
}
