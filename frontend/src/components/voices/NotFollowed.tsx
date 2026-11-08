import { Link } from 'react-router-dom';

import type { NotFollowedChannel } from '../../services/api';
import { sourceLabel } from '../../lib/sourceLabel';

/** The Add-source flow's entry for an address (the feed finder, prefilled): Sources with ?follow=<address>. */
export const followPath = (url: string) => `/sources?follow=${encodeURIComponent(url)}`;

/**
 * "Not followed: <channel> — Add" (issue 0132 C2): a voice's or a source's other channels you don't follow, each with
 * why (its profile links it, its own posts link it, Discover). Add opens the Add-source flow on its address; nothing
 * is ever added without you.
 */
export default function NotFollowed({ channels, onFollow }: { channels: NotFollowedChannel[]; onFollow?: (url: string) => void }) {
  if (!channels.length) return null;
  return (
    <ul className="flex flex-col gap-1" aria-label="Not followed">
      {channels.map((c) => (
        <li key={c.key} data-testid="not-followed" className="text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]">
          Not followed: <span className="font-semibold text-fg">{sourceLabel(c.label)}</span>
          {c.platform ? <span className="text-fg-3"> · {c.platform}{c.hosts ? ` · ${c.hosts} hosts` : ''}</span> : null}
          {' — '}
          {onFollow ? (
            <button type="button" className="underline decoration-fg-3 hover:text-fg" onClick={() => onFollow(c.url)}>Add</button>
          ) : (
            <Link to={followPath(c.url)} className="underline decoration-fg-3 hover:text-fg">Add</Link>
          )}
          <span className="block text-fg-3">
            {c.why.map((w, i) => (
              <span key={`${w.rule}-${i}`}>
                {i ? '; ' : ''}{w.line}
                {w.posts.map((id, k) => (
                  <span key={id}>{' '}<Link to={`/posts/${encodeURIComponent(id)}`} className="underline decoration-fg-3">post {k + 1}</Link></span>
                ))}
              </span>
            ))}
          </span>
        </li>
      ))}
    </ul>
  );
}
