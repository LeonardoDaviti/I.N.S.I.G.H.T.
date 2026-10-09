// tailwind.config.cjs
// CommonJS on purpose: Tailwind 3 reloads its config in a running dev server by
// clearing require.cache, which cannot evict an ES module on Node >= 22. As .cjs,
// edits here hot-reload in `vite` without a restart.
// Mark IX design language (plan/INSIGHT_mark_ix_design.md): monochrome only.
// Every colour resolves to a CSS variable defined in src/index.css, so one class
// works in dark (default) and light. The whole stock palette is replaced: grey and
// chromatic scales alike map onto one theme-aware neutral ramp, which turns every
// Mark VIII page monochrome without rewriting it. New code uses the semantic names
// (bg, surface, raised, line, fg, inverse), never the ramp.
const typography = require('@tailwindcss/typography');
const plugin = require('tailwindcss/plugin');

const STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const channel = (name) => `rgb(var(--${name}) / <alpha-value>)`;
const ramp = (prefix) => Object.fromEntries(STEPS.map((step) => [step, channel(`${prefix}-${step}`)]));

// Greys keep a smooth ramp; chromatic scales use a high-contrast "ink" ramp, so a
// Mark VIII `bg-blue-600 text-white` button becomes the inverted primary block and
// `text-indigo-700` becomes plain text instead of a washed-out grey.
const GREYS = ['slate', 'gray', 'zinc', 'neutral', 'stone'];
const CHROMATIC = [
  'red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald', 'teal', 'cyan',
  'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose',
];

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['class', '.theme-dark'],
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
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      inherit: 'inherit',
      black: '#000000',
      // `white` is "the page's light surface": white in light, the row surface in dark.
      white: channel('n-white'),
      ...Object.fromEntries(GREYS.map((name) => [name, ramp('n')])),
      ...Object.fromEntries(CHROMATIC.map((name) => [name, ramp('c')])),

      // Semantic tokens (the only names new code should use).
      bg: channel('bg'),
      surface: channel('surface'),
      raised: channel('raised'),
      line: { DEFAULT: channel('border'), strong: channel('border-strong') },
      fg: { DEFAULT: channel('text'), 2: channel('text-2'), 3: channel('text-3') },
      inverse: { DEFAULT: channel('inverse'), fg: channel('inverse-text') },

      // shadcn names, kept for the few places that use them.
      border: channel('border'),
      input: channel('border'),
      ring: channel('text'),
      background: channel('bg'),
      foreground: channel('text'),
      primary: { DEFAULT: channel('inverse'), foreground: channel('inverse-text') },
      secondary: { DEFAULT: channel('raised'), foreground: channel('text') },
      destructive: { DEFAULT: channel('inverse'), foreground: channel('inverse-text') },
      muted: { DEFAULT: channel('raised'), foreground: channel('text-2') },
      accent: { DEFAULT: channel('raised'), foreground: channel('text') },
      popover: { DEFAULT: channel('raised'), foreground: channel('text') },
      card: { DEFAULT: channel('surface'), foreground: channel('text') },
    },
    // No gradients anywhere: the `bg-gradient-*` utilities are not generated.
    backgroundImage: {
      none: 'none',
    },
    fontFamily: {
      sans: ['Inter', '"Inter Variable"', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', '"Helvetica Neue"', 'Arial', '"Noto Sans Arabic"', '"Noto Sans CJK JP"', '"Noto Sans"', 'sans-serif'],
      mono: ['ui-monospace', '"SF Mono"', '"JetBrains Mono"', 'Menlo', 'Consolas', '"Liberation Mono"', 'monospace'],
    },
    extend: {
      fontSize: {
        display: ['1.75rem', { lineHeight: '1.15', letterSpacing: '-0.025em', fontWeight: '650' }],
        title: ['1.375rem', { lineHeight: '1.25', letterSpacing: '-0.02em', fontWeight: '600' }],
        heading: ['1.0625rem', { lineHeight: '1.35', letterSpacing: '-0.01em', fontWeight: '600' }],
        body: ['0.9375rem', { lineHeight: '1.55' }],
        reading: ['1.125rem', { lineHeight: '1.7' }],
        small: ['0.8125rem', { lineHeight: '1.45', letterSpacing: '0.003em' }],
        micro: ['0.75rem', { lineHeight: '1.35', letterSpacing: '0.01em' }],
      },
      // Small radii (6px rows, 8px overlays). The large steps are clamped so the
      // Mark VIII rounded-2xl/3xl "bubble" cards lose their pastel shape.
      borderRadius: {
        sm: '0.25rem',
        DEFAULT: '0.375rem',
        md: '0.375rem',
        lg: '0.375rem',
        xl: '0.5rem',
        '2xl': '0.5rem',
        '3xl': '0.625rem',
      },
      // Flat surfaces; only overlays carry one neutral shadow.
      boxShadow: {
        sm: 'none',
        DEFAULT: 'none',
        md: 'none',
        lg: 'var(--shadow-overlay)',
        xl: 'var(--shadow-overlay)',
        '2xl': 'var(--shadow-overlay)',
        overlay: 'var(--shadow-overlay)',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.23, 1, 0.32, 1)',
      },
      spacing: {
        topbar: 'var(--topbar-h)',
      },
      maxWidth: {
        reading: '68ch',
      },
      // `prose` (the reading view) draws its colours from the tokens.
      typography: {
        DEFAULT: {
          css: {
            '--tw-prose-body': 'rgb(var(--text))',
            '--tw-prose-headings': 'rgb(var(--text))',
            '--tw-prose-lead': 'rgb(var(--text-2))',
            '--tw-prose-links': 'rgb(var(--text))',
            '--tw-prose-bold': 'rgb(var(--text))',
            '--tw-prose-counters': 'rgb(var(--text-2))',
            '--tw-prose-bullets': 'rgb(var(--text-3))',
            '--tw-prose-hr': 'rgb(var(--border))',
            '--tw-prose-quotes': 'rgb(var(--text))',
            '--tw-prose-quote-borders': 'rgb(var(--border-strong))',
            '--tw-prose-captions': 'rgb(var(--text-2))',
            '--tw-prose-code': 'rgb(var(--text))',
            '--tw-prose-pre-code': 'rgb(var(--text))',
            '--tw-prose-pre-bg': 'rgb(var(--surface))',
            '--tw-prose-th-borders': 'rgb(var(--border))',
            '--tw-prose-td-borders': 'rgb(var(--border))',
          },
        },
      },
    },
  },
  plugins: [
    typography,
    // `coarse:` = touch-first pointers, where hit areas grow to 44px (spec §F.6).
    plugin(({ addVariant }) => {
      addVariant('coarse', '@media (pointer: coarse)');
    }),
  ],
}
