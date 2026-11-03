import type { CSSProperties } from 'react';
import { Toaster as Sonner } from 'sonner';
import { useTheme } from '../ThemeProvider';

/**
 * The app's toaster: sonner, monochrome. No rich (coloured) toasts; the toast
 * reads as a raised surface with a hairline border, and error toasts carry the
 * word, not a hue. Bottom-right, out of the reader's way.
 */
const MONO_VARS = {
  '--normal-bg': 'rgb(var(--raised))',
  '--normal-border': 'rgb(var(--border-strong))',
  '--normal-text': 'rgb(var(--text))',
  '--success-bg': 'rgb(var(--raised))',
  '--success-border': 'rgb(var(--border-strong))',
  '--success-text': 'rgb(var(--text))',
  '--info-bg': 'rgb(var(--raised))',
  '--info-border': 'rgb(var(--border-strong))',
  '--info-text': 'rgb(var(--text))',
  '--warning-bg': 'rgb(var(--raised))',
  '--warning-border': 'rgb(var(--text))',
  '--warning-text': 'rgb(var(--text))',
  '--error-bg': 'rgb(var(--inverse))',
  '--error-border': 'rgb(var(--inverse))',
  '--error-text': 'rgb(var(--inverse-text))',
  '--border-radius': '0.5rem',
  fontFamily: 'inherit',
} as CSSProperties;

export default function Toaster() {
  const { theme } = useTheme();
  return (
    <Sonner
      theme={theme === 'theme-dark' ? 'dark' : 'light'}
      position="bottom-right"
      style={MONO_VARS}
      // Above a phone's home bar (issue 0073): sonner's own offsets, plus the safe area (0 elsewhere).
      offset={{ bottom: 'calc(24px + env(safe-area-inset-bottom))', right: 'calc(24px + env(safe-area-inset-right))' }}
      mobileOffset={{ bottom: 'calc(16px + env(safe-area-inset-bottom))' }}
      toastOptions={{ style: { fontSize: '0.875rem' } }}
    />
  );
}
