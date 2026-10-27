import { Dialog, DialogContent, Kbd, Switch } from '../ui';
import { useShortcutPreference } from '../../hooks/useShortcutPreference';
import { SHORTCUT_ROWS } from '../../lib/shortcuts';

/**
 * The `?` dialog: the key map plus the "Keyboard shortcuts" on/off switch
 * (WCAG 2.1.4). When off, only `?` stays bound. Built on the Dialog, Kbd and
 * Switch primitives, so it shares their scrim, surface and motion.
 */
export default function ShortcutHelp({ open, onOpenChange, feedContext = true }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** False on a post opened outside a feed: its post column leaves out the keys it does not bind. */
  feedContext?: boolean;
}) {
  const [enabled, setEnabled] = useShortcutPreference();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Keyboard shortcuts" className="w-[min(36rem,calc(100vw-2rem))]">
        <div className="mt-3 flex items-center justify-between gap-4 rounded-md border border-line px-3 py-2">
          <label htmlFor="reader-shortcuts-switch" className="text-sm text-fg">
            Single-key shortcuts
            <span className="block text-xs text-fg-2">When off, only ? stays active.</span>
          </label>
          <Switch id="reader-shortcuts-switch" checked={enabled} onCheckedChange={setEnabled} />
        </div>

        <table className="mt-4 w-full border-collapse text-left text-sm">
          <thead>
            <tr className="text-xs text-fg-3">
              <th scope="col" className="py-1.5 pr-3 font-medium">Key</th>
              <th scope="col" className="py-1.5 pr-3 font-medium">Feed</th>
              <th scope="col" className="py-1.5 font-medium">Post page</th>
            </tr>
          </thead>
          <tbody>
            {SHORTCUT_ROWS.map((row) => (
              <tr key={row.keys.join()} className="border-t border-line align-top">
                <td className="whitespace-nowrap py-2 pr-3">
                  <span className="inline-flex gap-1">{row.keys.map((key) => <Kbd key={key}>{key}</Kbd>)}</span>
                </td>
                <td className="py-2 pr-3 text-fg">{row.feed}</td>
                <td className="py-2 text-fg-2">{row.postNeedsFeed && !feedContext ? '—' : row.post}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </DialogContent>
    </Dialog>
  );
}
