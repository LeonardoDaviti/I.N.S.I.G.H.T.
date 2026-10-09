// tailwind.config.js
import typography from '@tailwindcss/typography';

/** @type {import('tailwindcss').Config} */
export default {
  // Spec F.7: hover styles only where a real pointer can hover, so a tap on touch
  // never leaves a sticky hover state. Emits @media (hover: hover) and (pointer: fine).
  future: {
    hoverOnlyWhenSupported: true,
  },
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // `prose` (the Mark IX reading view) draws its colours from the theme tokens,
      // so it follows light/dark mode instead of the plugin's fixed grays.
      typography: {
        DEFAULT: {
          css: {
            '--tw-prose-body': 'var(--text-normal)',
            '--tw-prose-headings': 'var(--text-normal)',
            '--tw-prose-lead': 'var(--text-muted)',
            '--tw-prose-links': 'var(--text-accent)',
            '--tw-prose-bold': 'var(--text-normal)',
            '--tw-prose-counters': 'var(--text-muted)',
            '--tw-prose-bullets': 'var(--text-faint)',
            '--tw-prose-hr': 'var(--background-modifier-border)',
            '--tw-prose-quotes': 'var(--text-normal)',
            '--tw-prose-quote-borders': 'var(--background-modifier-border)',
            '--tw-prose-captions': 'var(--text-muted)',
            '--tw-prose-code': 'var(--text-normal)',
            '--tw-prose-pre-code': 'var(--text-normal)',
            '--tw-prose-pre-bg': 'var(--background-secondary)',
            '--tw-prose-th-borders': 'var(--background-modifier-border)',
            '--tw-prose-td-borders': 'var(--background-modifier-border)',
          },
        },
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [typography],
}