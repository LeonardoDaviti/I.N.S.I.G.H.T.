import type { ReactNode } from 'react';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';

export type ThemeMode = 'theme-light' | 'theme-dark';

/** Dark (monochrome, black and white) is the default; light is the same system inverted. */
export const DEFAULT_THEME: ThemeMode = 'theme-dark';

type ThemeContextValue = {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
};

export const THEME_STORAGE_KEY = 'insight.theme';
const STORAGE_KEY = THEME_STORAGE_KEY;

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') {
      return DEFAULT_THEME;
    }
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === 'theme-light' || stored === 'theme-dark' ? stored : DEFAULT_THEME;
  });

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('theme-light', 'theme-dark', 'dark');
    root.classList.add(theme);
    if (theme === 'theme-dark') {
      root.classList.add('dark');
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'theme-dark' ? '#121212' : '#ffffff');
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const value = useMemo<ThemeContextValue>(() => ({
    theme,
    setTheme: (nextTheme) => setThemeState(nextTheme),
    toggleTheme: () => setThemeState((current) => (current === 'theme-dark' ? 'theme-light' : 'theme-dark')),
  }), [theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used inside ThemeProvider');
  }
  return context;
}
