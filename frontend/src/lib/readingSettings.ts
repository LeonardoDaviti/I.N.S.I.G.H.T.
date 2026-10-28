/**
 * Reading settings (issue 0045): the post text's font, size and column width,
 * per device. They scale the column and never pack it tighter: line height and
 * spacing stay as decided (one density, issue 0034), since the post body sets
 * them in `em` and unitless leading.
 *
 * Applied as CSS variables on the post page's frame. The default sets none, so
 * the page reads exactly as before: each use falls back to today's value.
 */

export type ReadingFont = 'sans' | 'serif';
export type ReadingSize = '1' | '2' | '3' | '4' | '5';
export type ReadingWidth = 'narrow' | 'standard' | 'wide';

export interface ReadingSettings {
  font: ReadingFont;
  size: ReadingSize;
  width: ReadingWidth;
}

export const READING_DEFAULTS: ReadingSettings = { font: 'sans', size: '3', width: 'standard' };

export const READING_FONTS: ReadonlyArray<{ value: ReadingFont; label: string }> = [
  { value: 'sans', label: 'Sans' },
  { value: 'serif', label: 'Serif' },
];

/** Five steps around today's size (1.0625rem on a phone, 1.125rem from sm up), as a multiplier. */
const SCALES: Record<ReadingSize, number> = { 1: 0.9, 2: 0.95, 3: 1, 4: 1.1, 5: 1.25 };
export const READING_SIZES: ReadonlyArray<{ value: ReadingSize; label: string }> = (
  ['1', '2', '3', '4', '5'] as const
).map((value) => ({ value, label: `${Math.round(SCALES[value] * 100)}%` }));

/** The column (rem, for the title and the text) and the text's measure (ch). Standard is today's. */
const WIDTHS: Record<ReadingWidth, { column: string; measure: string }> = {
  narrow: { column: '36rem', measure: '58ch' },
  standard: { column: '42rem', measure: '68ch' },
  wide: { column: '52rem', measure: '84ch' },
};
export const READING_WIDTHS: ReadonlyArray<{ value: ReadingWidth; label: string }> = [
  { value: 'narrow', label: 'Narrow' },
  { value: 'standard', label: 'Standard' },
  { value: 'wide', label: 'Wide' },
];

/** No webfont is shipped (system/typography.md): the serif is the system's, 0 bytes. */
export const SERIF_STACK = 'ui-serif, "Iowan Old Style", Charter, "Bitstream Charter", "Sitka Text", Cambria, Georgia, "Noto Serif", "Times New Roman", serif';

/** The post text's classes: the reading size scales it (its tables, figures and code are in em),
 *  the font and measure apply; with no variable set it is today's 1.0625rem (1.125rem from sm), 68ch. */
export const READING_TEXT_CLASS = 'max-w-[var(--reading-measure,68ch)] text-[length:calc(1.0625rem*var(--reading-scale,1))] leading-[1.7] text-fg [font-family:var(--reading-font)] sm:text-[length:calc(1.125rem*var(--reading-scale,1))]';

/** The CSS variables for `settings`; only the ones that differ from today, none for the default. */
export function readingStyle(settings: ReadingSettings): Record<string, string> | undefined {
  const style: Record<string, string> = {};
  if (settings.font === 'serif') style['--reading-font'] = SERIF_STACK;
  if (settings.size !== READING_DEFAULTS.size) style['--reading-scale'] = String(SCALES[settings.size]);
  if (settings.width !== READING_DEFAULTS.width) {
    style['--reading-column'] = WIDTHS[settings.width].column;
    style['--reading-measure'] = WIDTHS[settings.width].measure;
  }
  return Object.keys(style).length ? style : undefined;
}
