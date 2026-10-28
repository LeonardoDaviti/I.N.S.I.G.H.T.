import { Dialog, DialogContent } from '../ui/Dialog';
import ReadingSettingsPanel from './ReadingSettingsPanel';
import { useReadingSettings } from '../../hooks/useReadingSettings';
import { READING_TEXT_CLASS, readingStyle } from '../../lib/readingSettings';

/**
 * The reading settings from ⌘K (issue 0045), anywhere in the app: the same panel
 * as the post page's Aa popover, over a sample paragraph set as a post is.
 */
export default function ReadingSettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [settings] = useReadingSettings();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Reading settings"
        description="The font, size and width of a post's text, on this device."
        className="w-[min(36rem,calc(100vw-2rem))]"
      >
        <div className="mt-4">
          <ReadingSettingsPanel />
        </div>
        <div style={readingStyle(settings)} className="mt-4 overflow-hidden border-t border-line pt-4">
          <p data-reading-sample className={READING_TEXT_CLASS}>
            A post reads in one calm column. The size and the width scale that column; the space between the lines stays as it is.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
