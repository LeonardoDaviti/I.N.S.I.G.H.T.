import { forwardRef, type ComponentPropsWithoutRef, type ElementRef, type ReactNode } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';
import { iconButtonClass } from './styles';
import { overlayClass } from './Dialog';

/**
 * A side sheet (Radix dialog) for parallel tasks: editing a source, the reader
 * nav drawer. It slides in from the right edge and leaves the same way
 * (apple §7, spatial consistency); 260ms in, 200ms out, fade under reduced motion.
 */
export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

export const SheetContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { title: ReactNode; description?: ReactNode }
>(function SheetContent({ className, title, description, children, ...props }, ref) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={overlayClass} />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          'ui-sheet fixed inset-y-0 right-0 z-50 flex w-[min(28rem,100vw)] flex-col border-l border-line-strong bg-bg text-fg shadow-overlay focus:outline-none',
          className,
        )}
        {...props}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <DialogPrimitive.Title className="break-words text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em]">
              {title}
            </DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-1 text-[0.8125rem] text-fg-2">{description}</DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{typeof title === 'string' ? title : 'Panel'}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close aria-label="Close" className={cn(iconButtonClass, '-mr-2 -mt-1')}>
            <X aria-hidden="true" />
          </DialogPrimitive.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});
