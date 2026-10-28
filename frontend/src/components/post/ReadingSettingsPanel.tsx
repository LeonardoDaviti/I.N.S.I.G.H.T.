import SlashChoice from '../reader/SlashChoice';
import { useReadingSettings } from '../../hooks/useReadingSettings';
import { READING_FONTS, READING_SIZES, READING_WIDTHS } from '../../lib/readingSettings';

/**
 * The three reading settings (issue 0045): font, size and width, each a slash
 * choice. Every change applies at once to the post text behind (the live preview)
 * and is kept on this device. Loaded only when the Aa popover or ⌘K opens it.
 */
export default function ReadingSettingsPanel() {
  const [settings, set] = useReadingSettings();
  const rows = [
    { label: 'Font', choice: <SlashChoice label="Font" value={settings.font} options={READING_FONTS} onChange={(value) => set('font', value)} /> },
    { label: 'Size', choice: <SlashChoice label="Size" value={settings.size} options={READING_SIZES} onChange={(value) => set('size', value)} /> },
    { label: 'Width', choice: <SlashChoice label="Width" value={settings.width} options={READING_WIDTHS} onChange={(value) => set('width', value)} /> },
  ];
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <span aria-hidden="true" className="text-[0.8125rem] text-fg-3">{row.label}</span>
          <div className="-ml-1 min-w-0 overflow-x-auto">{row.choice}</div>
        </div>
      ))}
    </div>
  );
}
