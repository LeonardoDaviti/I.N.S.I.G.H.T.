import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';

import { useShortcutPreference } from '../../hooks/useShortcutPreference';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';

/** The one keyboard map (spec §F.5). `/` (search) is deliberately absent: search is deferred. */
export const SHORTCUT_ROWS: ReadonlyArray<{ keys: string[]; feed: string; post: string }> = [
  { keys: ['j', 'k'], feed: 'Next / previous item (loads more at the end)', post: 'Next / previous post in the feed' },
  { keys: ['o', 'Enter'], feed: 'Open the selected post (marks it read)', post: '—' },
  { keys: ['u', 'Esc'], feed: '—', post: 'Back to the feed' },
  { keys: ['m'], feed: 'Toggle read', post: 'Toggle read' },
  { keys: ['s'], feed: 'Toggle star', post: 'Toggle star' },
  { keys: ['Shift+A'], feed: 'Mark all read up to the selected item', post: '—' },
  { keys: ['f'], feed: 'Fetch this feed’s sources', post: 'Fetch this post’s source' },
  { keys: ['?'], feed: 'Show this help', post: 'Show this help' },
];

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex min-w-[1.75rem] items-center justify-center rounded-[0.25rem] border border-line-strong bg-surface px-1.5 py-0.5 font-mono text-xs text-fg">
      {children}
    </kbd>
  );
}

/**
 * The `?` dialog: the key map plus the "Keyboard shortcuts" on/off switch
 * (WCAG 2.1.4). When off, only `?` stays bound. Centred modal, a short fade and
 * scale entrance, a plain fade under reduced motion.
 */
export default function ShortcutHelp({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [enabled, setEnabled] = useShortcutPreference();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="ops-dialog-overlay fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          aria-describedby={undefined}
          className="ops-dialog-panel fixed left-1/2 top-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-line-strong bg-bg p-5"
        >
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="text-base font-semibold tracking-[-0.011em] text-fg">Keyboard shortcuts</Dialog.Title>
            <Dialog.Close
              aria-label="Close"
              className={`-mr-2 -mt-2 inline-flex h-9 w-9 items-center justify-center rounded-md text-fg-2 hover:bg-raised hover:text-fg coarse:h-11 coarse:w-11 ${PRESS_FEEDBACK} ${FOCUS_RING}`}
            >
              <X aria-hidden="true" className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <div className="mt-3 flex items-center justify-between gap-4 rounded-md border border-line px-3 py-2">
            <label htmlFor="reader-shortcuts-switch" className="text-sm text-fg">
              Single-key shortcuts
              <span className="block text-xs text-fg-2">When off, only ? stays active.</span>
            </label>
            <button
              id="reader-shortcuts-switch"
              type="button"
              role="switch"
              aria-checked={enabled}
              onClick={() => setEnabled(!enabled)}
              className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border ${enabled ? 'border-inverse bg-inverse' : 'border-line-strong bg-raised'} ${FOCUS_RING}`}
            >
              <span className="sr-only">{enabled ? 'On' : 'Off'}</span>
              <span
                aria-hidden="true"
                className={`absolute h-5 w-5 rounded-full ${enabled ? 'bg-inverse-fg' : 'bg-fg-2'} transition-transform duration-150 ease-out motion-reduce:transition-none ${enabled ? 'translate-x-[1.375rem]' : 'translate-x-0.5'}`}
              />
            </button>
          </div>

          <table className="mt-4 w-full border-collapse text-left text-sm">
            <thead>
              <tr className="text-xs text-fg-3">
                <th scope="col" className="py-1.5 pr-3 font-medium">Key</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Feed</th>
                <th scope="col" className="py-1.5 font-medium">Post page</th>
              </tr>
            </thead>
            <tbody>
              {SHORTCUT_ROWS.map((row) => (
                <tr key={row.keys.join()} className="border-t border-line align-top">
                  <td className="whitespace-nowrap py-2 pr-3">
                    <span className="inline-flex gap-1">{row.keys.map((key) => <Kbd key={key}>{key}</Kbd>)}</span>
                  </td>
                  <td className="py-2 pr-3 text-fg">{row.feed}</td>
                  <td className="py-2 text-fg-2">{row.post}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
