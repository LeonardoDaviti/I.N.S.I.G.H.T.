import { forwardRef, type ComponentPropsWithoutRef, type ElementRef, type ReactNode } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';
import { iconButtonClass } from './styles';

/**
 * Modal dialog (Radix): centered, solid raised surface over a scrim. Enters in
 * 200ms (opacity + scale 0.97→1, strong ease-out), exits faster; a plain fade
 * under reduced motion. `instant` drops the animation for surfaces used many
 * times a day (the ⌘K switcher).
 */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export const overlayClass = 'ui-overlay fixed inset-0 z-50 bg-[rgb(var(--scrim))]';

export const DialogContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    title: ReactNode;
    description?: ReactNode;
    /** Hide the title visually (it stays the accessible name). */
    hideTitle?: boolean;
    instant?: boolean;
    showClose?: boolean;
  }
>(function DialogContent(
  { className, title, description, hideTitle = false, instant = false, showClose = true, children, ...props },
  ref,
) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={cn(overlayClass, instant && 'ui-instant')} />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          'ui-dialog fixed left-1/2 top-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto',
          'rounded-lg border border-line-strong bg-raised p-5 text-fg shadow-overlay focus:outline-none',
          instant && 'ui-instant',
          className,
        )}
        {...props}
      >
        <DialogPrimitive.Title
          className={cn('pr-8 text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em]', hideTitle && 'sr-only')}
        >
          {title}
        </DialogPrimitive.Title>
        {description ? (
          <DialogPrimitive.Description className="mt-1.5 text-[0.875rem] text-fg-2">{description}</DialogPrimitive.Description>
        ) : (
          <DialogPrimitive.Description className="sr-only">{typeof title === 'string' ? title : 'Dialog'}</DialogPrimitive.Description>
        )}
        {children}
        {showClose ? (
          <DialogPrimitive.Close aria-label="Close" className={cn(iconButtonClass, 'absolute right-2 top-2')}>
            <X aria-hidden="true" />
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});

/** Right-aligned action row at the bottom of a dialog or sheet. */
export function DialogFooter({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('mt-5 flex flex-wrap justify-end gap-2', className)}>{children}</div>;
}
