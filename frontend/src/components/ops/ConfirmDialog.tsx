import * as Dialog from '@radix-ui/react-dialog';
import type { ReactNode } from 'react';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';

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
  const buttonBase = `inline-flex min-h-[44px] items-center justify-center rounded-lg px-4 text-sm font-medium ${PRESS_FEEDBACK} ${FOCUS_RING}`;
  return (
    <Dialog.Root open={open} onOpenChange={(next) => { if (!next) onCancel(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="ops-dialog-overlay fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          role="alertdialog"
          className="ops-dialog-panel fixed left-1/2 top-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-5 shadow-xl"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            (event.currentTarget as HTMLElement | null)?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
          }}
        >
          <Dialog.Title className="text-base font-semibold tracking-[-0.01em] text-[var(--text-normal)]">{title}</Dialog.Title>
          <Dialog.Description asChild>
            <div className="mt-2 break-words text-sm text-[var(--text-muted)]">{description}</div>
          </Dialog.Description>
          <div className="mt-5 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              data-cancel
              onClick={onCancel}
              className={`${buttonBase} border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] text-[var(--text-normal)] hover:bg-[var(--background-secondary-alt)]`}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              className={`${buttonBase} ${destructive
                ? 'bg-[var(--text-error)] text-white hover:opacity-90'
                : 'bg-[var(--interactive-accent)] text-[var(--text-on-accent)] hover:bg-[var(--interactive-accent-hover)]'}`}
            >
              {confirmLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
