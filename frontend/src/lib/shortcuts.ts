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
