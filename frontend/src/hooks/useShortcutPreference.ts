import { useCallback, useSyncExternalStore } from 'react';

/**
 * Small persisted UI choices for the reader (localStorage). One store shared by
 * every component, so flipping a switch in the shortcut help updates the feed's
 * key handling at once. Storage failures (private mode, quota) fall back to the
 * default and never throw.
 */
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (!event.key?.startsWith('insight.reader.')) return;
    // Another tab wrote it: its value replaces ours, so the in-memory copy
    // (kept only for when storage throws) must not shadow it.
    if (event.newValue === null) memory.delete(event.key);
    else memory.set(event.key, event.newValue);
    listener();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Not persisted; the in-memory value below still applies for this session.
  }
  memory.set(key, value);
  for (const listener of listeners) listener();
}

const memory = new Map<string, string>();

/** A persisted string choice limited to `allowed`. */
export function useStoredChoice<T extends string>(key: string, allowed: readonly T[], fallback: T): [T, (value: T) => void] {
  const getSnapshot = () => {
    const raw = memory.get(key) ?? readStored(key);
    return (allowed as readonly string[]).includes(raw ?? '') ? (raw as T) : fallback;
  };
  const value = useSyncExternalStore(subscribe, getSnapshot, () => fallback);
  const set = useCallback((next: T) => writeStored(key, next), [key]);
  return [value, set];
}

export const SHORTCUTS_KEY = 'insight.reader.shortcuts';

/** Single-key shortcuts on/off (WCAG 2.1.4). When off, only `?` stays bound. */
export function useShortcutPreference(): [boolean, (enabled: boolean) => void] {
  const [value, set] = useStoredChoice(SHORTCUTS_KEY, ['on', 'off'] as const, 'on');
  const setEnabled = useCallback((enabled: boolean) => set(enabled ? 'on' : 'off'), [set]);
  return [value === 'on', setEnabled];
}

export type ReadingFlow = 'continuous' | 'single';

/** How the post page goes on after a post: the next one follows below, or one at a time (issue 0014). */
export function useFlowPreference(): [ReadingFlow, (flow: ReadingFlow) => void] {
  return useStoredChoice('insight.reader.flow', ['continuous', 'single'] as const, 'continuous');
}

/** Test helper: forget in-memory values between tests. */
export function resetStoredChoices() {
  memory.clear();
  for (const listener of listeners) listener();
}
