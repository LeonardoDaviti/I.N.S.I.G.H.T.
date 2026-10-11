import type { ReactNode } from 'react';
import StatusGlyph from '../ui/StatusGlyph';
import TextLink from '../ui/TextLink';
import type { Status } from '../ui/styles';

/**
 * The one way to say "ingestion is (not) running", shared by the reader and
 * the ingestion tab so the same fact is drawn once. Monochrome (design docs system/status.md):
 * a solid 1px box, a shape and a word. Stopped is a hollow ring (nothing is
 * happening, not "loading"), failing is the inverted "×" chip, running a dot.
 */
export type IngestionState = 'stopped' | 'failing' | 'running';

const SPEC: Record<IngestionState, { glyph: Status; word: string; title: string; box: string }> = {
  stopped: { glyph: 'read', word: 'stopped', title: 'Ingestion is not running', box: 'border-fg' },
  failing: { glyph: 'failing', word: 'failing', title: 'Ingestion is failing', box: 'border-fg' },
  running: { glyph: 'ok', word: 'running', title: 'Ingestion is running', box: 'border-line' },
};

export default function IngestionStatusNotice({
  state,
  message,
  title,
  linkToIngestion = false,
  testId = 'ingestion-status-notice',
  className = '',
}: {
  state: IngestionState;
  message?: ReactNode;
  /** Overrides the default sentence ("Ingestion is not running"). */
  title?: ReactNode;
  /** Pages other than /ingestion point at it. */
  linkToIngestion?: boolean;
  testId?: string;
  className?: string;
}) {
  const spec = SPEC[state];
  return (
    <div
      role="status"
      data-testid={testId}
      data-state={state}
      className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-md border bg-bg px-4 py-3 text-[0.875rem] ${spec.box} ${className}`}
    >
      <StatusGlyph status={spec.glyph} label={spec.word} className={state === 'stopped' ? 'text-fg font-semibold' : undefined} />
      <div className="min-w-0 flex-1 basis-[16rem]">
        <p className="break-words font-semibold text-fg">{title ?? spec.title}</p>
        {message ? <div className="mt-0.5 break-words text-fg-2 [overflow-wrap:anywhere]">{message}</div> : null}
      </div>
      {linkToIngestion ? (
        <TextLink to="/ingestion" className="shrink-0">
          Open ingestion
        </TextLink>
      ) : null}
    </div>
  );
}
