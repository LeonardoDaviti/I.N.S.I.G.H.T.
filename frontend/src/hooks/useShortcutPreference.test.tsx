import { afterEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { resetStoredChoices, SHORTCUTS_KEY, useShortcutPreference } from './useShortcutPreference';

afterEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('useShortcutPreference', () => {
  it('follows a change made in another tab after this tab wrote a value', () => {
    const { result } = renderHook(() => useShortcutPreference());
    act(() => result.current[1](false));
    expect(result.current[0]).toBe(false);

    // Another tab turns shortcuts back on: localStorage changes, then a storage event arrives.
    act(() => {
      window.localStorage.setItem(SHORTCUTS_KEY, 'on');
      window.dispatchEvent(new StorageEvent('storage', { key: SHORTCUTS_KEY, newValue: 'on' }));
    });
    expect(result.current[0]).toBe(true);
  });
});
