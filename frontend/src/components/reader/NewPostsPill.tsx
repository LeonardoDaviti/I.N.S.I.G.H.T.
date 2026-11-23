import { ArrowUp } from 'lucide-react';

import { plural } from '../../lib/format';
import { FOCUS_RING, PRESS_FEEDBACK } from '../states';

/** "N new posts, show": new posts never land on top of a list being read; clicking reloads the feed and scrolls to
 *  the top. */
export default function NewPostsPill({ count, onShow }: { count: number; onShow: () => void }) {
  if (count <= 0) return null;
  return (
    <button
      type="button"
      onClick={onShow}
      className={`reader-pill inline-flex min-h-[2.25rem] items-center gap-1.5 whitespace-nowrap rounded-md bg-inverse px-3 text-[0.8125rem] font-semibold text-inverse-fg tabular-nums hover:bg-inverse/85 coarse:min-h-[2.75rem] ${PRESS_FEEDBACK} ${FOCUS_RING}`}
    >
      <ArrowUp aria-hidden="true" className="h-4 w-4" />
      {plural(count, 'new post')}
      <span className="sr-only">, show</span>
    </button>
  );
}
