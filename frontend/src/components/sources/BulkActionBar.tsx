import { useId } from 'react';
import { X } from 'lucide-react';

import type { Folder } from '../../services/api';
import { formatCount } from '../../lib/format';
import { Button } from '../ui';

/**
 * Appears while sources are selected: a small floating bar at the bottom
 * centre (translucent, one short ease-out in; none under reduced motion).
 * Enable, disable, add to a track, delete; Esc or × clears the selection.
 */
export default function BulkActionBar({
  count,
  folders,
  busy,
  onEnable,
  onAddToTrack,
  onDelete,
  onClear,
}: {
  count: number;
  folders: Pick<Folder, 'id' | 'name'>[];
  busy: boolean;
  onEnable: (enabled: boolean) => void;
  onAddToTrack: (folderId: string) => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  const trackId = useId();
  if (count === 0) return null;
  return (
    <div
      role="region"
      aria-label="Selected sources"
      className="material fixed inset-x-0 bottom-4 z-40 mx-auto flex w-max max-w-[calc(100vw-1.5rem)] flex-wrap items-center gap-1 rounded-lg border border-line-strong px-2 py-1.5 text-[0.8125rem] shadow-overlay motion-safe:animate-[pop-in_160ms_cubic-bezier(0.23,1,0.32,1)]"
    >
      <span className="px-2 font-semibold tabular-nums text-fg" aria-live="polite">{formatCount(count)} selected</span>
      <Button variant="ghost" size="sm" disabled={busy} onClick={() => onEnable(true)}>Enable</Button>
      <Button variant="ghost" size="sm" disabled={busy} onClick={() => onEnable(false)}>Disable</Button>
      {folders.length ? (
        <>
          <label htmlFor={trackId} className="sr-only">Add to track</label>
          <select
            id={trackId}
            value=""
            disabled={busy}
            onChange={(event) => { if (event.target.value) onAddToTrack(event.target.value); }}
            className="h-8 max-w-[11rem] cursor-pointer rounded-md border border-transparent bg-transparent px-2 text-[0.8125rem] font-medium text-fg-2 hover:bg-raised hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg"
          >
            <option value="">Add to track…</option>
            {folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
          </select>
        </>
      ) : null}
      <Button variant="ghost" size="sm" disabled={busy} onClick={onDelete}>Delete…</Button>
      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClear} aria-label="Clear selection" title="Clear selection (Esc)">
        <X aria-hidden="true" />
      </Button>
    </div>
  );
}
