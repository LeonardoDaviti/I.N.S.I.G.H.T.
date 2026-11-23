import { ArrowDown, ArrowLeft, ArrowUp } from 'lucide-react';
import { Button } from '../ui';

interface PostNavProps {
  label: string;
  /** `sm` for the sticky row under the top bar, `lg` (a tap target) after the article. */
  size: 'sm' | 'lg';
  backLabel: string;
  onBack: () => void;
  /** Previous and Next, with a feed context only; a null side is disabled. */
  step?: { onPrevious: (() => void) | null; onNext: (() => void) | null };
}

/** The sticky row also holds the post's actions and Aa, so under 640px Back, Previous and Next keep only their
 *  arrows there (the words stay their names). */
const STEP_LABEL = 'max-sm:sr-only';

/** Back / Previous / Next on the post page, on one line at every width. */
export default function PostNav({ label, size, backLabel, onBack, step }: PostNavProps) {
  return (
    <nav aria-label={label} className="-ml-2.5 flex min-w-0 flex-nowrap items-center gap-1">
      <Button variant="ghost" size={size} onClick={onBack} title="Back (u)">
        <ArrowLeft aria-hidden="true" />
        <span className={size === 'sm' ? STEP_LABEL : undefined}>{backLabel}</span>
      </Button>
      {step ? (
        <>
          <Button variant="ghost" size={size} onClick={step.onPrevious ?? undefined} disabled={!step.onPrevious} title="Previous post (k)">
            <ArrowUp aria-hidden="true" />
            <span className={size === 'sm' ? STEP_LABEL : undefined}>Previous</span>
          </Button>
          <Button variant="ghost" size={size} onClick={step.onNext ?? undefined} disabled={!step.onNext} title="Next post (j)">
            <ArrowDown aria-hidden="true" />
            <span className={size === 'sm' ? STEP_LABEL : undefined}>Next</span>
          </Button>
        </>
      ) : null}
    </nav>
  );
}
