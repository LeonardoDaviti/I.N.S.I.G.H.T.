import * as Dialog from '@radix-ui/react-dialog';
import type { ReactNode } from 'react';
import { Button } from '../ui';

/**
 * A confirmation for a consequential action (a forced run, a delete). Modal,
 * centred, an `alertdialog`; focus starts on Cancel so Enter never confirms by
 * accident. The overlay and panel fade/scale in under 200ms with a strong
 * ease-out, and only fade when the user prefers reduced motion (spec §F.7).
 */
export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  destructive = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => { if (!next) onCancel(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="ops-dialog-overlay fixed inset-0 z-50 bg-[rgb(var(--scrim))]" />
        <Dialog.Content
          role="alertdialog"
          className="ops-dialog-panel fixed left-1/2 top-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line-strong bg-raised p-5 text-fg shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            (event.currentTarget as HTMLElement | null)?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
          }}
        >
          <Dialog.Title className="flex items-start gap-2.5 text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">
            {destructive ? (
              // Monochrome destructive mark: an inverted block with ×, never a hue.
              <span aria-hidden="true" className="mt-[0.1875rem] inline-flex h-[1.125rem] w-[1.125rem] shrink-0 items-center justify-center rounded-sm bg-inverse text-[0.8125rem] leading-none text-inverse-fg">
                ×
              </span>
            ) : null}
            <span className="min-w-0 break-words">{title}</span>
          </Dialog.Title>
          <Dialog.Description asChild>
            <div className="mt-2 break-words text-[0.875rem] text-fg-2">{description}</div>
          </Dialog.Description>
          <div className="mt-5 flex flex-wrap justify-end gap-2">
            <Button variant="secondary" data-cancel onClick={onCancel}>
              Cancel
            </Button>
            <Button variant={destructive ? 'danger' : 'primary'} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
