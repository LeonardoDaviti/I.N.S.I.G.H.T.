import type { ReactNode } from 'react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { ArrowUpRight, Check, Clock, Copy, MessageSquare, Star } from 'lucide-react';
import { cn } from '../../lib/utils';
import { buttonVariants } from '../ui';

/**
 * The post's actions, icon-only, in the post page's sticky band left of Aa: open the original, open its discussion
 * (when the feed names one), read later and keep (whatever the read state), copy the text. Each has a tooltip and an
 * aria-label.
 */
// Concatenated, not merged: tailwind-merge would drop the base focus outline. `[&:active:not(:focus-visible)]`
// outranks the base `active:` scale, so a key press does not scale the button.
const ICON_ACTION = [
  buttonVariants({ variant: 'ghost', size: 'icon' }),
  '[&:focus-visible:active]:scale-100 motion-reduce:[&:active]:scale-100',
  '[&_svg]:!h-[1.125rem] [&_svg]:!w-[1.125rem]',
  // the band's height (2rem, as Back and Aa), narrower under 360px so the row never overflows
  '!h-8 !w-8 max-[359px]:!w-7',
].join(' ');

const TIP = cn(
  'z-50 select-none rounded-[4px] bg-inverse px-2 py-1 text-[0.75rem] font-medium leading-none text-inverse-fg',
  'data-[state=delayed-open]:animate-[fade-in_125ms_ease-out] motion-reduce:animate-none',
);

function Action({ tip, children }: { tip: string; children: ReactNode }) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side="bottom" sideOffset={6} className={TIP}>
          {tip}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

export interface PostActionsProps {
  url?: string | null;
  discussionUrl?: string | null;
  starred: boolean;
  starring: boolean;
  onStar: () => void;
  later: boolean;
  onLater: () => void;
  copied: boolean;
  onCopy: () => void;
}

export default function PostActions({ url, discussionUrl, starred, starring, onStar, later, onLater, copied, onCopy }: PostActionsProps) {
  return (
    <Tooltip.Provider delayDuration={500} skipDelayDuration={400}>
      <div role="group" aria-label="Post actions" className="flex shrink-0 items-center">
        {url ? (
          <Action tip="Open original">
            <a href={url} target="_blank" rel="noopener noreferrer" aria-label="Open original" className={ICON_ACTION}>
              <ArrowUpRight aria-hidden="true" />
            </a>
          </Action>
        ) : null}
        {discussionUrl ? (
          <Action tip="Open discussion">
            <a href={discussionUrl} target="_blank" rel="noopener noreferrer" aria-label="Open discussion" className={ICON_ACTION}>
              <MessageSquare aria-hidden="true" />
            </a>
          </Action>
        ) : null}
        <Action tip={later ? 'In Later: take it out (l)' : 'Read later (l)'}>
          <button
            type="button"
            aria-label="Read later"
            aria-pressed={later}
            onClick={onLater}
            className={later ? `${ICON_ACTION} !text-fg` : ICON_ACTION}
          >
            <Clock aria-hidden="true" strokeWidth={later ? 2.75 : 2} />
          </button>
        </Action>
        <Action tip={starred ? 'Kept (s)' : 'Keep (s)'}>
          <button
            type="button"
            aria-label="Keep"
            aria-pressed={starred}
            aria-busy={starring || undefined}
            onClick={() => { if (!starring) onStar(); }}
            className={starred ? `${ICON_ACTION} !text-fg` : ICON_ACTION}
          >
            <Star aria-hidden="true" className={starred ? 'fill-current' : undefined} />
          </button>
        </Action>
        <Action tip={copied ? 'Copied' : 'Copy text'}>
          <button type="button" aria-label={copied ? 'Copied' : 'Copy text'} onClick={onCopy} className={ICON_ACTION}>
            {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          </button>
        </Action>
      </div>
    </Tooltip.Provider>
  );
}
