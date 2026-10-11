/** The one keyboard map (spec §F.5). `/` (search) is deliberately absent: search is deferred. */
export const SHORTCUT_ROWS: ReadonlyArray<{ keys: string[]; feed: string; post: string }> = [
  { keys: ['j', 'k'], feed: 'Next / previous item (loads more at the end)', post: 'Next / previous post in the feed' },
  { keys: ['o', 'Enter'], feed: 'Open the selected post (marks it read)', post: '—' },
  { keys: ['u', 'Esc'], feed: '—', post: 'Back to the feed' },
  { keys: ['m'], feed: 'Toggle read', post: 'Toggle read' },
  { keys: ['s'], feed: 'Toggle star', post: 'Toggle star' },
  { keys: ['Shift+A'], feed: 'Mark all read up to the selected item', post: '—' },
  { keys: ['?'], feed: 'Show this help', post: 'Show this help' },
];

/** A key press that belongs to a form field or an editor, not to the page. */
export function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]'));
}

/**
 * Inside an open dialog the dialog owns the keyboard (Esc closes it, Enter
 * confirms). `menus: true` counts an open menu too, as the Sources list does.
 */
export function isInDialog(target: EventTarget | null, { menus = false }: { menus?: boolean } = {}): boolean {
  const selector = menus ? '[role="dialog"], [role="alertdialog"], [role="menu"]' : '[role="dialog"], [role="alertdialog"]';
  return target instanceof HTMLElement && Boolean(target.closest(selector));
}
