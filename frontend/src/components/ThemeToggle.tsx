import { MoonStar, SunMedium } from 'lucide-react';
import { useTheme } from './ThemeProvider';

export default function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'theme-dark';

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className="theme-toggle"
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      <span className={`theme-toggle__option ${!isDark ? 'is-active' : ''}`}>
        <SunMedium className="h-4 w-4" />
        Light
      </span>
      <span className={`theme-toggle__option ${isDark ? 'is-active' : ''}`}>
        <MoonStar className="h-4 w-4" />
        Dark
      </span>
    </button>
  );
}
