import { useEffect, useRef } from 'react';

import { isEditable, isInDialog } from '../lib/shortcuts';

/** Every key the reader binds (spec §F.5). `A` means Shift+A. */
export type ShortcutKey = 'j' | 'k' | 'o' | 'Enter' | 'm' | 's' | 'l' | 'u' | 'Escape' | 'A' | '?';

export type ShortcutBindings = Partial<Record<ShortcutKey, () => void>>;

const BOUND = new Set<string>(['j', 'k', 'o', 'Enter', 'm', 's', 'l', 'u', 'Escape', 'A', '?']);

/**
 * Bind the reader's single-key shortcuts on `document` (spec §F.5). Ignored while
 * focus is in a form field or a dialog, and while Ctrl, Alt or Meta is held. When
 * `singleKeys` is false (the WCAG 2.1.4 switch) only `?` stays bound. Enter is left
 * to the browser on links and buttons, so it never double-fires.
 */
export function useKeyboardShortcuts(
  bindings: ShortcutBindings,
  { enabled = true, singleKeys = true }: { enabled?: boolean; singleKeys?: boolean } = {},
) {
  const ref = useRef(bindings);
  ref.current = bindings;

  useEffect(() => {
    if (!enabled) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.isComposing || isEditable(event.target) || isInDialog(event.target)) return;
      const key = event.key;
      if (!BOUND.has(key)) return;
      if (key === 'A' && !event.shiftKey) return;
      if (key !== '?' && !singleKeys) return;
      if (key === 'Enter' && event.target instanceof HTMLElement && event.target.closest('a, button, summary')) return;
      const handler = ref.current[key as ShortcutKey];
      if (!handler) return;
      event.preventDefault();
      handler();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [enabled, singleKeys]);
}
