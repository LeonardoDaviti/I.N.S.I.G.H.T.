import { Fragment, useState } from 'react';
import type { ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { MarkxFoldAnswer, MarkxFoldScore, MarkxLine } from '../../services/markx';
import { Button } from '../ui';
import { errorMessage } from '../../lib/apiError';

/** 0127 (Mark X v10.3): duplicates folded. The words of the owner's answers. */
const FOLD_WORDS: Record<Exclude<MarkxFoldAnswer, 'undo'>, string> = {
  same: 'same happening',
  not_same: 'not the same',
};

/**
 * The buttons on a member's fold (like the entity queue's: applied at once, stored as a label): on a folded post
 * "same happening ✓" / "not the same ✗"; on a member outside the group "fold: same happening"; after an answer,
 * "you: …" and undo. The page is read again, so the post moves in or out of its group.
 */
export function FoldTap({ line }: { line: MarkxLine }) {
  const api = useApi();
  const client = useQueryClient();
  const fold = line.fold;
  const [answer, setAnswer] = useState(fold?.answer ?? null);
  const tap = useMutation({
    mutationFn: (a: MarkxFoldAnswer) => api.answerMarkxFold(line.story as string, line.id, a),
    onSuccess: (got) => {
      setAnswer(got.answer ?? null);
      void client.invalidateQueries({ queryKey: ['markx-news'] });
    },
  });
  if (!fold || !line.story || fold.state === 'head') return null;
  if (answer) {
    return (
      <span className="mt-1 flex flex-wrap items-center gap-2 text-[0.75rem] text-fg-2">
        <span data-fold-answer={answer}>you: {FOLD_WORDS[answer]}</span>
        <Button size="sm" variant="ghost" disabled={tap.isPending} onClick={() => tap.mutate('undo')}>undo</Button>
      </span>
    );
  }
  const asks: { a: Exclude<MarkxFoldAnswer, 'undo'>; words: string }[] = fold.state === 'folded'
    ? [{ a: 'same', words: 'same happening ✓' }, { a: 'not_same', words: 'not the same ✗' }]
    : [{ a: 'same', words: 'fold: same happening' }];
  return (
    <span className="mt-1 flex flex-wrap items-center gap-2" role="group" aria-label="Does it retell the same happening?">
      {asks.map(({ a, words }) => (
        <Button key={a} size="sm" variant="ghost" disabled={tap.isPending} onClick={() => tap.mutate(a)}
          className="text-[0.75rem]">{words}</Button>
      ))}
      {tap.isError ? <span role="alert" className="text-[0.75rem] text-fg">{errorMessage(tap.error)}</span> : null}
    </span>
  );
}

/**
 * A row's posts with each group folded: the head shows as before, then one line "↳ N more retell it" opens the
 * posts folded under it (indented). A folded post whose head isn't in the row shows as any other line.
 */
export function FoldedPosts({ lines, render }: { lines: MarkxLine[]; render: (line: MarkxLine, extra: ReactNode) => ReactNode }) {
  const ids = new Set(lines.map((line) => line.id));
  const under = new Map<string, MarkxLine[]>();
  for (const line of lines) {
    const head = line.fold?.state === 'folded' ? line.fold.head : null;
    if (head && ids.has(head) && head !== line.id) under.set(head, [...(under.get(head) ?? []), line]);
  }
  const folded = new Set([...under.values()].flat().map((line) => line.id));
  return (
    <>
      {lines.filter((line) => !folded.has(line.id)).map((line) => {
        const kids = under.get(line.id) ?? [];
        return (
          <Fragment key={line.id}>
            {render(line, <FoldTap line={line} />)}
            {kids.length ? (
            <li className="border-t border-line py-1.5" data-fold-group={line.id}>
              <details>
                <summary className="cursor-pointer text-[0.8125rem] leading-5 text-fg-2">
                  ↳ {kids.length} more {kids.length === 1 ? 'retells' : 'retell'} it
                </summary>
                <ul aria-label="Retold" className="ml-4 border-l border-line pl-3">
                  {kids.map((kid) => render(kid, <FoldTap line={kid} />))}
                </ul>
              </details>
            </li>
            ) : null}
          </Fragment>
        );
      })}
    </>
  );
}

/** The header's line: the lab's number, then the owner's own count once there are labels. */
export function FoldHeader({ score }: { score: MarkxFoldScore }) {
  const { folded, missed, lab } = score;
  return (
    <p className="mt-2 text-[0.75rem] leading-5 text-fg-3" data-folds>
      Duplicates folded: experimental; on unseen lab stories F1 {lab.f1.toFixed(2)} (lab, {lab.date})
      {folded.n ? ` · your labels: ${folded.right} of ${folded.n} folds right` : ''}
      {missed ? ` · ${missed} missed` : ''}
    </p>
  );
}
