import { TextLink } from '../ui';
import type { MarkxChain, MarkxChainLink, MarkxChainRelation } from '../../services/markx';

const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

/** How the linked story relates, read from the page's story's side (0219). `before`: the page follows from it. */
const BEFORE: Record<MarkxChainRelation, string> = {
  same_release: 'earlier in this release', same_event: 'the same event, filed earlier', follows_up: 'this follows up on it',
  development: 'this develops it', reaction: 'this reacts to it', builds_on: 'this builds on it',
};
const AFTER: Record<MarkxChainRelation, string> = {
  same_release: 'later in this release', same_event: 'the same event, filed later', follows_up: 'follows up on this',
  development: 'develops this', reaction: 'reacts to this', builds_on: 'builds on this',
};

function Link({ link, words }: { link: MarkxChainLink; words: Record<MarkxChainRelation, string> }) {
  return (
    <li className="min-w-0 py-1 text-[0.8125rem] text-fg-2" data-relation={link.relation} data-depth={link.depth}>
      <div className="flex min-w-0 gap-3">
        <span className="w-[5.5rem] shrink-0 tabular-nums text-fg-3">{link.first_at ? link.first_at.slice(0, 10) : ''}</span>
        <span className="min-w-0 [overflow-wrap:anywhere]">
          <TextLink to={`/markx/stories/${encodeURIComponent(link.story)}`}>{link.headline || 'A story'}</TextLink>
          <span className="text-fg-3"> · {words[link.relation]}{link.depth > 1 ? ' · via a linked story' : ''}</span>
          {link.reason ? <span className="block text-[0.75rem] leading-5 text-fg-3" dir="auto">{link.reason}</span> : null}
        </span>
      </div>
    </li>
  );
}

/**
 * A story's chain (0219): the stories about the same thing that led to it and those that followed, each link typed and
 * explained by the judge's reason, nearest first. Shown only when there is a link; only the relations that passed their
 * bar reach the page.
 */
export function StoryChain({ chain }: { chain?: MarkxChain | null }) {
  if (!chain || (!chain.before.length && !chain.after.length)) return null;
  const side = (label: string, links: MarkxChainLink[], more: number, words: Record<MarkxChainRelation, string>) =>
    links.length ? (
      <div>
        <h3 className="mt-2 text-[0.75rem] font-semibold uppercase tracking-wide text-fg-3">{label}</h3>
        <ul>{links.map((l) => <Link key={l.story} link={l} words={words} />)}</ul>
        {more ? <p className="text-[0.75rem] text-fg-3">+{more} more</p> : null}
      </div>
    ) : null;
  return (
    <section aria-label="Chain">
      <h2 className={H2}>Chain{chain.as_of ? ` · as of ${chain.as_of.slice(0, 10)}` : ''}</h2>
      {side('Led to it', chain.before, chain.before_more, BEFORE)}
      {side('Followed', chain.after, chain.after_more, AFTER)}
    </section>
  );
}
