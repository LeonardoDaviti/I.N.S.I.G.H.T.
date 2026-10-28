/**
 * Keyboard navigation over a feed (spec §F.3, §F.5), as a pure reducer.
 *
 * Selection is held by post id, never by index, so a page appended at the end or
 * new posts prepended on top never move it to a different item. Actions that need
 * the outside world (focus the row, load the next page, toggle read, Later or Keep, open,
 * mark read up to here) come back as one `intent` on the new state; the caller
 * performs it. A reducer cannot fire effects, and this keeps it testable.
 */

export type NavIntent =
  | { kind: 'focus'; id: string }
  | { kind: 'loadMore' }
  | { kind: 'open'; id: string }
  | { kind: 'toggleRead'; id: string }
  | { kind: 'toggleStar'; id: string }
  | { kind: 'toggleLater'; id: string }
  | { kind: 'markThrough'; id: string };

export type NavAction =
  | { type: 'sync'; ids: readonly string[]; hasMore: boolean }
  | { type: 'next' }
  | { type: 'prev' }
  | { type: 'select'; id: string; /** Also focus and scroll to it (coming back from a post). */ focus?: boolean }
  | { type: 'open' }
  | { type: 'toggleRead' }
  | { type: 'toggleStar' }
  | { type: 'toggleLater' }
  | { type: 'markThrough' };

export interface NavState {
  ids: readonly string[];
  selectedId: string | null;
  hasMore: boolean;
  /** j was pressed at the last loaded item: advance once the next page arrives. */
  pendingAdvance: boolean;
  intent: NavIntent | null;
}

export function initialNavState(ids: readonly string[] = [], hasMore = false): NavState {
  return { ids, selectedId: null, hasMore, pendingAdvance: false, intent: null };
}

function moveTo(state: NavState, id: string): NavState {
  return { ...state, selectedId: id, pendingAdvance: false, intent: { kind: 'focus', id } };
}

function selectedIntent(state: NavState, kind: 'open' | 'toggleRead' | 'toggleStar' | 'toggleLater' | 'markThrough'): NavState {
  if (!state.selectedId) return { ...state, intent: null };
  return { ...state, intent: { kind, id: state.selectedId } };
}

function sameIds(a: readonly string[], b: readonly string[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return false;
  return true;
}

export function feedNavigation(state: NavState, action: NavAction): NavState {
  switch (action.type) {
    case 'sync': {
      const ids = action.ids;
      // Same ids and the same paging: nothing to do. Returning the same object
      // lets the caller skip a render (a read/star patch re-syncs an equal list).
      if (!state.pendingAdvance && !state.intent && state.hasMore === action.hasMore && sameIds(state.ids, ids)) return state;
      let next: NavState = { ...state, ids, hasMore: action.hasMore, intent: null };
      if (state.selectedId && !ids.includes(state.selectedId)) {
        // The selected item left the list: take whatever now sits where it was.
        const oldIndex = state.ids.indexOf(state.selectedId);
        const fallback = ids.length ? ids[Math.min(Math.max(oldIndex, 0), ids.length - 1)] : null;
        next = { ...next, selectedId: fallback, pendingAdvance: false };
      }
      if (state.pendingAdvance && next.selectedId) {
        const index = ids.indexOf(next.selectedId);
        if (index >= 0 && index < ids.length - 1) return moveTo(next, ids[index + 1]);
        if (!action.hasMore) next = { ...next, pendingAdvance: false };
      }
      return next;
    }
    case 'next': {
      const { ids, selectedId } = state;
      if (!ids.length) return { ...state, intent: state.hasMore ? { kind: 'loadMore' } : null };
      const index = selectedId ? ids.indexOf(selectedId) : -1;
      if (index < 0) return moveTo(state, ids[0]);
      if (index < ids.length - 1) return moveTo(state, ids[index + 1]);
      if (state.hasMore) return { ...state, pendingAdvance: true, intent: { kind: 'loadMore' } };
      return { ...state, intent: null };
    }
    case 'prev': {
      const { ids, selectedId } = state;
      if (!ids.length) return { ...state, intent: null };
      const index = selectedId ? ids.indexOf(selectedId) : -1;
      if (index < 0) return moveTo(state, ids[0]);
      if (index > 0) return moveTo(state, ids[index - 1]);
      return { ...state, intent: null };
    }
    case 'select':
      if (!state.ids.includes(action.id)) return { ...state, intent: null };
      if (action.focus) return moveTo(state, action.id);
      return { ...state, selectedId: action.id, pendingAdvance: false, intent: null };
    case 'open':
      return selectedIntent(state, 'open');
    case 'toggleRead':
      return selectedIntent(state, 'toggleRead');
    case 'toggleStar':
      return selectedIntent(state, 'toggleStar');
    case 'toggleLater':
      return selectedIntent(state, 'toggleLater');
    case 'markThrough':
      return selectedIntent(state, 'markThrough');
    default:
      return state;
  }
}
