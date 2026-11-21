import { TextLink } from '../ui';
import type { MarkxChain, MarkxChainLink, MarkxChainRelation, MarkxRowChain, MarkxRowChainLink } from '../../services/markx';

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

const byDate = <T extends { first_at: string | null; story: string }>(links: T[]) =>
  [...links].sort((a, b) => (a.first_at ?? '').localeCompare(b.first_at ?? '') || a.story.localeCompare(b.story));

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
 * A story's Earlier and Later (0219, 0267): the stories about the same thing before it and after it, each link with its
 * relation in plain words and the judge's reason, in date order. Shown only when there is a link; only the relations
 * that passed their bar reach the page.
 */
export function StoryChain({ chain }: { chain?: MarkxChain | null }) {
  if (!chain || (!chain.before.length && !chain.after.length)) return null;
  const side = (label: string, links: MarkxChainLink[], more: number, words: Record<MarkxChainRelation, string>) =>
    links.length ? (
      <div>
        <h3 className="mt-2 text-[0.75rem] font-semibold text-fg-3">{label}</h3>
        <ul>{byDate(links).map((l) => <Link key={l.story} link={l} words={words} />)}</ul>
        {more ? <p className="text-[0.75rem] text-fg-3">+{more} more</p> : null}
      </div>
    ) : null;
  return (
    <section aria-label="Earlier and later">
      <h2 className={H2}>Earlier and later{chain.as_of ? ` · as of ${chain.as_of.slice(0, 10)}` : ''}</h2>
      {side('Earlier', chain.before, chain.before_more, BEFORE)}
      {side('Later', chain.after, chain.after_more, AFTER)}
    </section>
  );
}

/** 0267: a News row's Earlier and Later, one plain line a story (the row's own stories left out). */
export function RowChain({ chain }: { chain?: MarkxRowChain | null }) {
  if (!chain || (!chain.before.length && !chain.after.length)) return null;
  const line = (label: string, l: MarkxRowChainLink, words: Record<MarkxChainRelation, string>) => (
    <li key={`${label}-${l.story}`} className="text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]"
      data-relation={l.relation}>
      <span className="text-fg-3">{label}: </span>
      <TextLink to={`/markx/stories/${encodeURIComponent(l.story)}`}>{l.headline || 'A story'}</TextLink>
      <span className="text-fg-3">{l.first_at ? ` · ${l.first_at.slice(0, 10)}` : ''} · {words[l.relation]}</span>
    </li>
  );
  const more = chain.before_more + chain.after_more;
  return (
    <ul aria-label="Earlier and later" className="mb-2">
      {byDate(chain.before).map((l) => line('Earlier', l, BEFORE))}
      {byDate(chain.after).map((l) => line('Later', l, AFTER))}
      {more ? <li className="text-[0.75rem] text-fg-3">+{more} more on the story page</li> : null}
    </ul>
  );
}
