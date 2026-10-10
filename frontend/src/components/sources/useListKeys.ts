import { useEffect, useRef } from 'react';

export type ListKey = 'j' | 'k' | 'x' | 'o' | 'Enter' | 'Escape' | '/';
const BOUND = new Set<string>(['j', 'k', 'x', 'o', 'Enter', 'Escape', '/']);

function isEditable(target: EventTarget | null): boolean {
  return target instanceof HTMLElement
    && (target.isContentEditable || Boolean(target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]')));
}

function isInDialog(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest('[role="dialog"], [role="alertdialog"], [role="menu"]'));
}

/**
 * The Sources list keys: j/k move, x selects, o/Enter opens, Esc clears the
 * selection, / focuses search. Same guards as the reader: never inside a form
 * field, a dialog or a menu, never with Ctrl/Alt/Meta, and single keys only
 * while the reader's shortcut switch (WCAG 2.1.4) is on. Enter on a button is
 * left to the button. The keys also work from a row's checkbox.
 */
export function useListKeys(bindings: Partial<Record<ListKey, () => void>>, singleKeys: boolean) {
  const ref = useRef(bindings);
  ref.current = bindings;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
      const key = event.key;
      if (!BOUND.has(key) || isInDialog(event.target)) return;
      // A checkbox is not a text field: the list keys work from it (Space still toggles it natively).
      const checkbox = event.target instanceof HTMLInputElement && event.target.type === 'checkbox';
      if (isEditable(event.target) && !checkbox) return;
      if (key !== 'Escape' && !singleKeys) return;
      if (key === 'Enter' && event.target instanceof HTMLElement && event.target.closest('a, button, summary')) return;
      const handler = ref.current[key as ListKey];
      if (!handler) return;
      event.preventDefault();
      handler();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [singleKeys]);
}
