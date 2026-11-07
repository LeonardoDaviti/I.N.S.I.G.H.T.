import type { MarkxLine, MarkxRow, MarkxStoryPost, MarkxStoryView } from '../../services/markx';
import type { MarkxBuilt, MarkxBuiltLine, MarkxOriginalHow } from '../../services/api';
import { TextLink } from '../ui';

/** 0128 (Stealth v10.4): how a Mark X story is built. The shapes the News row and the story view carry. */
export type BuiltRow = MarkxRow & { built?: MarkxBuilt | null };
export type BuiltLine = MarkxLine & { built?: MarkxBuiltLine | null };
export type BuiltStoryView = MarkxStoryView & { built?: MarkxBuilt | null };

export const EVENT_WORDS: Record<string, string> = {
  model_release: 'model release',
  product_release: 'product release',
  research_result: 'research result',
  business_event: 'business news',
  policy_legal: 'policy or legal',
  incident: 'incident',
  public_statement: 'statement',
  promotion_event: 'event or promotion',
  leak_rumour: 'leak or rumour',
  opinion_analysis: 'opinion',
  tutorial_explainer: 'explainer',
  digest: 'digest',
  community_post: 'community post',
  other: 'other',
};

const HOW_WORDS: Record<MarkxOriginalHow, string> = {
  links: 'by links: the page the others link',
  maker: 'by its maker: the maker’s own post',
  'maker-page': 'by its maker: the maker’s page',
  'maker-link': 'by its maker: a link to the maker’s page',
};

/** The measured numbers the header states (0128, the lab's unseen clusters, 2026-11-07). */
export const BUILT_LAB = 'Experimental: the original shown first is right on 61% of the lab’s unseen clusters '
  + '(82–88% among their real members); event types are 74% right a post; leak links come only from Mark X’s own connections.';

function hours(h: number): string {
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} days`;
}

/** "model release · 5 of 6 read": the row's summary words (empty while no member is read). */
export function eventWords(b: MarkxBuilt | null | undefined): string {
  if (!b || !b.event_type) return '';
  return EVENT_WORDS[b.event_type] ?? b.event_type.replace(/_/g, ' ');
}

/** A line's role in how its story is built: the original (and how it was found), or a leak before the release. */
export function LineRole({ role }: { role: MarkxBuiltLine | null | undefined }) {
  if (!role) return null;
  if (role.role === 'original') {
    return <span className="block text-[0.75rem] font-medium leading-5 text-fg" data-built="original">original · {HOW_WORDS[role.how]}</span>;
  }
  const what = role.own_coverage
    ? 'leaked with coverage of its own: by the rule its own story, linked “came true” (not split yet)'
    : 'joins the release';
  return (
    <span className="block text-[0.75rem] font-medium leading-5 text-fg" data-built="leak">
      leak · {hours(role.hours)} before the release · {what}
    </span>
  );
}

/** "Came true in" (on a leak story) and "Leaked earlier" (on a release story), each opening the other story. */
export function CameTrue({ built }: { built: MarkxBuilt | null | undefined }) {
  if (!built || (!built.came_true.length && !built.leaked_before.length)) return null;
  return (
    <div className="mt-2 space-y-1 text-[0.8125rem] leading-5 text-fg-2" data-built="links">
      {built.came_true.map((x) => (
        <p key={`t-${x.story}`}>
          Came true: <TextLink to={`/markx/stories/${encodeURIComponent(x.story)}`}>{x.headline || 'the release'}</TextLink>
          <span className="text-fg-3"> · {hours(x.hours)} later{x.joins ? ' · joins it' : ''}</span>
        </p>
      ))}
      {built.leaked_before.map((x) => (
        <p key={`l-${x.story}`}>
          {x.joins ? 'Leaked hours before (joins this story)' : 'Leaked earlier'}:{' '}
          <TextLink to={`/markx/stories/${encodeURIComponent(x.story)}`}>{x.headline || 'the leak'}</TextLink>
          <span className="text-fg-3"> · {hours(x.hours)} before</span>
        </p>
      ))}
    </div>
  );
}

/**
 * The story page's "How it was built" (0128): the event type, the original first (or the source page), the leaks
 * before the release and the stories linked "came true", with the measured accuracy.
 */
export function BuiltSection({ built, posts }: { built: MarkxBuilt | null | undefined; posts: Record<string, MarkxStoryPost> }) {
  if (!built) return null;
  const first = built.original ? posts[built.original.post] : undefined;
  return (
    <section aria-label="How it was built" className="space-y-2">
      <h2 className="border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2">How it was built</h2>
      <p className="text-[0.75rem] leading-5 text-fg-3">{BUILT_LAB}</p>
      <p className="text-[0.8125rem] leading-5 text-fg-2">
        {built.event_type ? <span data-event-type={built.event_type}>{eventWords(built)}</span> : 'no event type yet'}
        {` · ${built.read.read} of ${built.read.members} read`}
      </p>
      {first ? (
        <p className="text-[0.875rem] leading-5 text-fg [overflow-wrap:anywhere]" data-built="first">
          <span className="text-fg-3">First: </span>
          <TextLink to={`/posts/${encodeURIComponent(first.id)}`}>{first.title || '(no title)'}</TextLink>
          <span className="text-fg-3"> · {first.source} · {HOW_WORDS[built.original!.how]}</span>
        </p>
      ) : built.source_page ? (
        <p className="text-[0.8125rem] leading-5 text-fg-2 [overflow-wrap:anywhere]" data-built="source-page">
          No post is the original; the source page: {built.source_page}
        </p>
      ) : null}
      {built.leaks.length ? (
        <ul aria-label="Before the release" className="text-[0.8125rem] leading-5 text-fg-2">
          {built.leaks.map((x) => (
            <li key={x.post}>
              <TextLink to={`/posts/${encodeURIComponent(x.post)}`} muted>{posts[x.post]?.title || 'a leak'}</TextLink>
              <span className="text-fg-3"> · leak, {hours(x.hours)} before the release
                {x.own_coverage ? ' · coverage of its own: by the rule its own story (not split yet)' : ' · joins'}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <CameTrue built={built} />
    </section>
  );
}
