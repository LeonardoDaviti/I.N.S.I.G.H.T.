import { Link } from 'react-router-dom';

import type { AlsoOnLine } from '../../services/api';
import { feedDateLabel } from '../../lib/dates';
import { sourceLabel } from '../../lib/sourceLabel';

/**
 * "Also on <channel>" (issue 0132 A): the same post on another channel of one voice, within 72 hours, shows once.
 * The earliest is the row; each other is one quiet line under it, a link to that post.
 */
export default function AlsoOn({ lines, now }: { lines: AlsoOnLine[]; now?: Date }) {
  if (!lines.length) return null;
  return (
    <ul data-also-on className="mt-0.5 flex flex-col gap-0.5">
      {lines.map((line) => (
        <li key={line.id} className="min-w-0 text-[0.8125rem] leading-5 text-fg-3">
          <Link to={`/posts/${encodeURIComponent(line.id)}`} className="underline decoration-transparent hover:decoration-fg-3 [overflow-wrap:anywhere]">
            Also on {sourceLabel(line.source_display_name)}
          </Link>
          <span> · {feedDateLabel(line.sort_at, now)}</span>
        </li>
      ))}
    </ul>
  );
}
