import { useCallback, useMemo } from 'react';
import { useStoredChoice } from './useShortcutPreference';
import {
  READING_DEFAULTS, READING_FONTS, READING_SIZES, READING_WIDTHS,
  type ReadingFont, type ReadingSettings, type ReadingSize, type ReadingWidth,
} from '../lib/readingSettings';

export const READING_KEYS = {
  font: 'insight.reader.font',
  size: 'insight.reader.size',
  width: 'insight.reader.width',
} as const;

const FONTS = READING_FONTS.map((option) => option.value);
const SIZES = READING_SIZES.map((option) => option.value);
const WIDTHS = READING_WIDTHS.map((option) => option.value);

export type SetReadingSetting = <K extends keyof ReadingSettings>(key: K, value: ReadingSettings[K]) => void;

/**
 * The post text's font, size and width (issue 0045), per device in local storage:
 * the reader's stored-choice store, so the Aa popover and the page change together.
 */
export function useReadingSettings(): [ReadingSettings, SetReadingSetting] {
  const [font, setFont] = useStoredChoice<ReadingFont>(READING_KEYS.font, FONTS, READING_DEFAULTS.font);
  const [size, setSize] = useStoredChoice<ReadingSize>(READING_KEYS.size, SIZES, READING_DEFAULTS.size);
  const [width, setWidth] = useStoredChoice<ReadingWidth>(READING_KEYS.width, WIDTHS, READING_DEFAULTS.width);
  const settings = useMemo(() => ({ font, size, width }), [font, size, width]);
  const set = useCallback<SetReadingSetting>((key, value) => {
    if (key === 'font') setFont(value as ReadingFont);
    else if (key === 'size') setSize(value as ReadingSize);
    else setWidth(value as ReadingWidth);
  }, [setFont, setSize, setWidth]);
  return [settings, set];
}
